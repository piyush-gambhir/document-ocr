"""
Shared utilities for generating synthetic, labelled KYC document images.

Used by the per-document generators in `scripts/generate_synthetic_<doc>.py` and
by the end-to-end accuracy benchmark `benchmarks/document_accuracy.py`.

Design:
  * Generators render *clean* card images (PIL) with known ground-truth field
    values and write a per-document `manifest.json` describing each image.
  * The benchmark loads each clean image, applies a fixed set of DEGRADATIONS
    (blur / rotate / noise / JPEG / low-res) in memory, runs the real OCR
    pipeline on each variant, and scores extracted fields against ground truth.

All identities are fictitious. Nothing here touches real PII.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "sample-documents"

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_FONT_CANDIDATES: dict[str, list[str]] = {
    "sans": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "sans_bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "mono": [
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ],
}


def load_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font by logical style ('sans' | 'sans_bold' | 'mono')."""
    for path in _FONT_CANDIDATES.get(style, []):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Card canvas — a thin convenience wrapper over PIL for laying out fields
# ---------------------------------------------------------------------------

_GREY = (90, 90, 90)
_BLACK = (0, 0, 0)


class Card:
    """A simple card canvas with label/value field helpers.

    Coordinates are pixels. `field_row` draws a label and its value either to the
    right ("right" — the common 'Label : value' card layout) or below ("below" —
    older laminated layouts), which is what the spatial extractors expect.
    """

    def __init__(self, width: int = 1000, height: int = 640, bg: str = "white"):
        self.width = width
        self.height = height
        self.img = Image.new("RGB", (width, height), bg)
        self.draw = ImageDraw.Draw(self.img)
        self._sans = {}
        self._mono = {}
        self._bold = {}

    def _font(self, style: str, size: int) -> ImageFont.FreeTypeFont:
        cache = {"sans": self._sans, "mono": self._mono, "sans_bold": self._bold}[style]
        if size not in cache:
            cache[size] = load_font(style, size)
        return cache[size]

    def text(self, x: int, y: int, s: str, *, style: str = "sans", size: int = 24, fill=_BLACK):
        self.draw.text((x, y), s, font=self._font(style, size), fill=fill)

    def header(self, x: int, y: int, s: str, *, size: int = 28):
        self.draw.text((x, y), s, font=self._font("sans_bold", size), fill=_BLACK)

    def line(self, x1: int, y1: int, x2: int, y2: int, *, width: int = 2, fill=_BLACK):
        self.draw.line((x1, y1, x2, y2), fill=fill, width=width)

    def rect(self, x1: int, y1: int, x2: int, y2: int, *, outline=_GREY, fill=None, width: int = 2):
        self.draw.rectangle((x1, y1, x2, y2), outline=outline, fill=fill, width=width)

    def photo_box(self, x: int, y: int, w: int, h: int):
        """A grey placeholder for the holder photo (OCR ignores it)."""
        self.draw.rectangle((x, y, x + w, y + h), outline=_GREY, fill=(220, 220, 220), width=2)

    def field_row(
        self,
        x: int,
        y: int,
        label: str,
        value: str,
        *,
        mode: str = "right",
        label_size: int = 20,
        value_size: int = 24,
        value_style: str = "sans",
        gap: int = 16,
        line_gap: int = 30,
    ):
        """Draw 'label' then 'value' (to the right or below). Returns next y."""
        label_font = self._font("sans", label_size)
        self.draw.text((x, y), label, font=label_font, fill=_GREY)
        if mode == "right":
            label_w = self.draw.textlength(label, font=label_font)
            self.draw.text(
                (x + int(label_w) + gap, y), value,
                font=self._font(value_style, value_size), fill=_BLACK,
            )
            return y + line_gap
        # below
        self.draw.text(
            (x, y + label_size + 6), value,
            font=self._font(value_style, value_size), fill=_BLACK,
        )
        return y + label_size + value_size + 14

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.img.save(path)


# ---------------------------------------------------------------------------
# Degradations (applied in-memory by the benchmark)
# ---------------------------------------------------------------------------

def _to_pil(img) -> Image.Image:
    if isinstance(img, Image.Image):
        return img
    return Image.fromarray(img)


def deg_identity(img: Image.Image) -> Image.Image:
    return img


def deg_blur(img: Image.Image, radius: float = 1.1) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def deg_rotate(img: Image.Image, degrees: float = 3.0) -> Image.Image:
    return img.rotate(degrees, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)


def deg_noise(img: Image.Image, sigma: float = 12.0) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    noise = np.random.default_rng(12345).normal(0.0, sigma, arr.shape)
    out = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def deg_jpeg(img: Image.Image, quality: int = 40) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def deg_lowres(img: Image.Image, scale: float = 0.6) -> Image.Image:
    w, h = img.size
    small = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)
    return small.resize((w, h), Image.BILINEAR)


# name -> callable(PIL.Image) -> PIL.Image. Parameters are intentionally moderate
# so a robust pipeline can still read most fields; the benchmark reports per-variant.
DEGRADATIONS: dict[str, Callable[[Image.Image], Image.Image]] = {
    "clean": deg_identity,
    "blur": deg_blur,
    "rotate_cw": lambda im: deg_rotate(im, -3.0),
    "rotate_ccw": lambda im: deg_rotate(im, 3.0),
    "noise": deg_noise,
    "jpeg": deg_jpeg,
    "lowres": deg_lowres,
}


def degrade(img, name: str) -> Image.Image:
    return DEGRADATIONS[name](_to_pil(img))


def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    _to_pil(img).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Manifest schema
# ---------------------------------------------------------------------------

@dataclass
class LabelledImage:
    """One labelled synthetic image: relative path + document type + ground-truth fields."""
    file: str                      # path relative to REPO_ROOT, e.g. 'sample-documents/pan/pan_01.png'
    document_type: str             # 'pan' | 'aadhaar' | 'driving_licence' | 'voter_id'
    fields: dict                   # ground-truth, camelCase keys matching the *Fields JSON block

    def to_dict(self) -> dict:
        return {"file": self.file, "documentType": self.document_type, "fields": self.fields}


def write_manifest(doc_type: str, items: list[LabelledImage]) -> Path:
    """Write sample-documents/<doc_type>/manifest.json and return its path."""
    out_dir = DATASET_DIR / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "manifest.json"
    path.write_text(json.dumps([it.to_dict() for it in items], indent=2) + "\n")
    return path


def load_all_manifests() -> list[LabelledImage]:
    """Load every sample-documents/*/manifest.json into LabelledImage records."""
    items: list[LabelledImage] = []
    if not DATASET_DIR.exists():
        return items
    for manifest in sorted(DATASET_DIR.glob("*/manifest.json")):
        for entry in json.loads(manifest.read_text()):
            items.append(
                LabelledImage(
                    file=entry["file"],
                    document_type=entry["documentType"],
                    fields=entry.get("fields", {}),
                )
            )
    return items
