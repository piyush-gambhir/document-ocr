"""
Image preprocessing for passport OCR.

Accepts a raw image (file path or bytes). Returns a clean, normalised image
ready for OCR after document detection, perspective correction, and
quality checks.
"""

from __future__ import annotations

import io

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_RESOLUTION = 600          # shortest dimension must be >= this
BLUR_THRESHOLD = 80           # Laplacian variance below this → blurry
GLARE_V_THRESHOLD = 250       # HSV V channel threshold for glare
GLARE_PIXEL_RATIO = 0.15      # reject if > 15 % pixels exceed V threshold
TARGET_WIDTH = 1600            # normalise output to this width
CLAHE_CLIP = 2.0
CLAHE_GRID = (8, 8)

# Document-detection sanity thresholds. Polygon approximation can produce
# degenerate quads from noise (perforations, watermarks, form-field rectangles).
# A real document boundary should cover most of the frame and be roughly
# convex with a passport-like aspect ratio.
MIN_QUAD_AREA_RATIO = 0.30    # quad must cover ≥ 30 % of image area
MIN_QUAD_ASPECT = 0.5         # reject very narrow / very tall quads
MAX_QUAD_ASPECT = 3.0
MIN_WARPED_AREA_RATIO = 0.50  # if perspective-corrected image is < 50 %
                              # of the input area, discard and use raw


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PreprocessResult:
    image: np.ndarray
    warnings: list[str] = field(default_factory=list)
    # Same geometry and resolution as image, without contrast enhancement.
    # Retained for bounded rereads when security backgrounds worsen with CLAHE.
    unenhanced_image: Optional[np.ndarray] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_image(source: Union[str, bytes, Path]) -> np.ndarray:
    """Load image from file path, bytes, or Path and return BGR numpy array."""
    # Decode paths and uploads identically: OpenCV's path/byte decoders do not
    # consistently handle EXIF orientation or HEIF, especially for phone photos.
    data = Path(source).read_bytes() if isinstance(source, (str, Path)) else source
    if data.startswith(b"%PDF-"):
        return _load_pdf_first_page(data)
    try:
        try:
            image = Image.open(io.BytesIO(data))
        except UnidentifiedImageError:
            import pillow_heif

            pillow_heif.register_heif_opener()
            image = Image.open(io.BytesIO(data))
        with image:
            if image.width * image.height > 40_000_000:
                raise ImageQualityError("IMAGE_TOO_LARGE")
            oriented = ImageOps.exif_transpose(image)
            pixels = np.asarray(oriented)
            if pixels.dtype.kind == "u" and pixels.dtype.itemsize == 2:
                # Pillow's direct RGB conversion clips 16-bit grayscale at 255,
                # erasing nearly all contrast. Match 8-bit image decoding by
                # retaining the high byte across the full 16-bit range.
                oriented = Image.fromarray((pixels >> 8).astype(np.uint8))
            return cv2.cvtColor(np.array(oriented.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Image.DecompressionBombError as exc:
        raise ImageQualityError("IMAGE_TOO_LARGE") from exc
    except (OSError, ValueError) as exc:
        raise ImageQualityError("INVALID_IMAGE") from exc


def _load_pdf_first_page(source: Union[str, bytes, Path]) -> np.ndarray:
    """Render a bounded first PDF page in the common 1600-pixel coordinate plane."""
    from .document_input import input_bytes, pdf_pages
    return pdf_pages(input_bytes(source), first_only=True)[0].image


def _check_resolution(img: np.ndarray) -> None:
    h, w = img.shape[:2]
    # Card scans can retain readable text at ~800 x 480. Keep the existing
    # general threshold while admitting a bounded compact-card size; blur and
    # extraction completeness still have to pass independently.
    compact_card = min(h, w) >= 450 and max(h, w) >= 750
    if min(h, w) < MIN_RESOLUTION and not compact_card:
        raise ImageQualityError("RESOLUTION_TOO_LOW")


def _check_blur(img: np.ndarray, threshold: float = BLUR_THRESHOLD) -> None:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    if variance < threshold:
        raise ImageQualityError("IMAGE_TOO_BLURRY")


def _check_glare(img: np.ndarray) -> Optional[str]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    ratio = np.count_nonzero(v_channel > GLARE_V_THRESHOLD) / v_channel.size
    if ratio > GLARE_PIXEL_RATIO:
        return "GLARE_DETECTED"
    return None


def _detect_document(img: np.ndarray) -> tuple[np.ndarray | None, list[str]]:
    """Find the document quadrilateral. Returns (corners, warnings).

    Only accepts a 4-corner approximation that is plausibly an entire
    document: large enough, convex, and with a passport-like aspect ratio.
    Without these checks, polygon approximation of noise contours
    (perforations, form-field rectangles, watermark edges) can produce
    degenerate quads that destroy the image during perspective correction.
    """
    warnings: list[str] = []
    h, w = img.shape[:2]
    img_area = float(h * w)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # dilate to close gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        warnings.append("NO_DOCUMENT_BOUNDARY_DETECTED")
        return None, warnings

    # sort by area descending
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for cnt in contours[:5]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        if _is_plausible_document_quad(approx, img_area):
            return approx.reshape(4, 2).astype(np.float32), warnings

    warnings.append("NO_DOCUMENT_BOUNDARY_DETECTED")
    return None, warnings


def _is_plausible_document_quad(approx: np.ndarray, img_area: float) -> bool:
    """A real document quad covers most of the image, is convex, and has a
    sane aspect ratio. Anything else is almost certainly a noise contour."""
    if not cv2.isContourConvex(approx):
        return False
    if cv2.contourArea(approx) < img_area * MIN_QUAD_AREA_RATIO:
        return False
    _, _, bw, bh = cv2.boundingRect(approx)
    if bw <= 0 or bh <= 0:
        return False
    aspect = bw / bh
    return MIN_QUAD_ASPECT <= aspect <= MAX_QUAD_ASPECT


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order points: top-left, top-right, bottom-right, bottom-left."""
    # Sorting each extremum separately can select the same vertex twice when
    # sums/differences tie (for example a document rotated by 45 degrees).
    points = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = np.lexsort((ordered[:, 0], ordered[:, 1], ordered.sum(axis=1)))[0]
    return np.roll(ordered, -start, axis=0)


def _perspective_correct(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Apply perspective transform to produce a flat, top-down crop."""
    rect = _order_points(corners)
    (tl, tr, br, bl) = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_w = int(max(width_a, width_b))

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_h = int(max(height_a, height_b))

    dst = np.array([
        [0, 0],
        [max_w - 1, 0],
        [max_w - 1, max_h - 1],
        [0, max_h - 1],
    ], dtype=np.float32)

    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(img, matrix, (max_w, max_h))


def _resize(img: np.ndarray) -> np.ndarray:
    """Use the same coordinate plane for enhanced and original-color reads."""
    h, w = img.shape[:2]
    if w > TARGET_WIDTH:
        ratio = TARGET_WIDTH / w
        new_h = int(h * ratio)
        img = cv2.resize(img, (TARGET_WIDTH, new_h), interpolation=cv2.INTER_LANCZOS4)
    return img


def _normalise(img: np.ndarray) -> np.ndarray:
    """Downscale to standard width (if larger) and apply CLAHE contrast enhancement."""
    return enhance_contrast(_resize(img))


def enhance_contrast(img: np.ndarray) -> np.ndarray:
    """Enhance contrast without resizing or moving any evidence coordinates."""

    # CLAHE on L channel in LAB
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ImageQualityError(Exception):
    """Raised when image quality is insufficient for OCR."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess(
    source: Union[str, bytes, Path],
    *,
    blur_threshold: float = BLUR_THRESHOLD,
) -> PreprocessResult:
    """
    Full preprocessing pipeline.

    1. Load image
    2. Resolution check
    3. Blur detection
    4. Glare detection
    5. Document detection + perspective correction
    6. Normalisation (resize + CLAHE)
    """
    img = _load_image(source)
    _check_resolution(img)
    _check_blur(img, threshold=blur_threshold)
    glare_warning = _check_glare(img)

    corners, warnings = _detect_document(img)
    if min(img.shape[:2]) < MIN_RESOLUTION:
        warnings.append("COMPACT_CARD_RESOLUTION")

    if glare_warning:
        warnings.append(glare_warning)

    if corners is not None:
        original_area = img.shape[0] * img.shape[1]
        warped = _perspective_correct(img, corners)
        warped_area = warped.shape[0] * warped.shape[1]
        if warped_area >= original_area * MIN_WARPED_AREA_RATIO:
            img = warped
        else:
            # Perspective transform produced a degenerate strip — the detected
            # quad must have been bogus. Discard it and use the raw image.
            warnings.append("PERSPECTIVE_CORRECTION_DISCARDED")

    unenhanced = _resize(img)
    img = _normalise(unenhanced)

    return PreprocessResult(image=img, warnings=warnings, unenhanced_image=unenhanced)
