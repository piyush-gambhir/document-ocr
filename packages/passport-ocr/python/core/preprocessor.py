"""
Image preprocessing for passport OCR.

Accepts a raw image (file path or bytes). Returns a clean, normalised image
ready for OCR after document detection, perspective correction, and
quality checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np
from PIL import Image

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


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PreprocessResult:
    image: np.ndarray
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_image(source: Union[str, bytes, Path]) -> np.ndarray:
    """Load image from file path, bytes, or Path and return BGR numpy array."""
    if isinstance(source, (str, Path)):
        path = str(source)
        if path.lower().endswith(".pdf"):
            return _load_pdf_first_page(path)
        if path.lower().endswith(".heic"):
            return _load_heic(path)
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Could not read image at {path}")
        return img

    # bytes
    arr = np.frombuffer(source, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image from bytes")
    return img


def _load_pdf_first_page(path: str) -> np.ndarray:
    """Extract first page of a PDF as an image."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for PDF support: pip install pymupdf")
    doc = fitz.open(path)
    page = doc[0]
    pix = page.get_pixmap(dpi=300)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    doc.close()
    return img


def _load_heic(path: str) -> np.ndarray:
    """Load HEIC image via pillow-heif."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        raise ImportError("pillow-heif is required for HEIC support: pip install pillow-heif")
    pil_img = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _check_resolution(img: np.ndarray) -> None:
    h, w = img.shape[:2]
    if min(h, w) < MIN_RESOLUTION:
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
    """Find largest quadrilateral in the image. Returns (corners, warnings)."""
    warnings: list[str] = []
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
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32), warnings

    warnings.append("NO_DOCUMENT_BOUNDARY_DETECTED")
    return None, warnings


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order points: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


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


def _normalise(img: np.ndarray) -> np.ndarray:
    """Downscale to standard width (if larger) and apply CLAHE contrast enhancement."""
    h, w = img.shape[:2]
    if w > TARGET_WIDTH:
        ratio = TARGET_WIDTH / w
        new_h = int(h * ratio)
        img = cv2.resize(img, (TARGET_WIDTH, new_h), interpolation=cv2.INTER_LANCZOS4)

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
    pass


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

    if glare_warning:
        warnings.append(glare_warning)

    if corners is not None:
        img = _perspective_correct(img, corners)

    img = _normalise(img)

    return PreprocessResult(image=img, warnings=warnings)
