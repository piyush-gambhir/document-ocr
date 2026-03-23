"""
PaddleOCR wrapper. Accepts a preprocessed image, returns detected text regions.

Supports PaddleOCR v3 (paddleocr>=3) API only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class TextRegion:
    text: str
    bbox: list[list[int]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    confidence: float


# ---------------------------------------------------------------------------
# Singleton OCR instance (initialisation is expensive ~3-5s)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_ocr_instances: dict[str, object] = {}


def _get_ocr(lang: str = "en"):
    """Get or create a cached PaddleOCR instance."""
    from paddleocr import PaddleOCR

    if lang not in _ocr_instances:
        with _lock:
            if lang not in _ocr_instances:
                _ocr_instances[lang] = PaddleOCR(
                    use_angle_cls=True,
                    lang=lang,
                )
    return _ocr_instances[lang]


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _parse_v3_results(results) -> list[TextRegion]:
    """Parse PaddleOCR v3 output format (dict with rec_texts, rec_scores, dt_polys)."""
    regions: list[TextRegion] = []

    if not results:
        return regions

    if isinstance(results, dict):
        results = [results]

    for page_result in results:
        if not isinstance(page_result, dict):
            continue

        texts = page_result.get("rec_texts", [])
        scores = page_result.get("rec_scores", [])
        polys = page_result.get("dt_polys", [])

        for i in range(len(texts)):
            text = str(texts[i]).strip()
            conf = float(scores[i]) if i < len(scores) else 0.0
            bbox = []
            if i < len(polys):
                poly = polys[i]
                if hasattr(poly, 'tolist'):
                    poly = poly.tolist()
                bbox = [[int(p[0]), int(p[1])] for p in poly[:4]]
            if text:
                regions.append(TextRegion(text=text, bbox=bbox, confidence=conf))

    return regions


# ---------------------------------------------------------------------------
# Script detection
# ---------------------------------------------------------------------------

def _is_likely_non_latin(regions: list[TextRegion]) -> bool:
    """Heuristic: if > 40% of characters in detected text are non-ASCII, re-run
    with multilingual model."""
    all_text = "".join(r.text for r in regions)
    if not all_text:
        return False
    non_ascii = sum(1 for c in all_text if ord(c) > 127)
    return (non_ascii / len(all_text)) > 0.4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_ocr(
    image: np.ndarray,
    *,
    lang: Optional[str] = None,
) -> list[TextRegion]:
    """
    Run OCR on a preprocessed image.

    Args:
        image: BGR numpy array (preprocessed).
        lang: Force a language. If None, starts with 'en' and falls back to
              'multilingual' if non-Latin script is detected.

    Returns:
        List of TextRegion with text, bounding box, and confidence.
    """
    use_lang = lang or "en"
    ocr = _get_ocr(use_lang)

    results = ocr.predict(image)
    regions = _parse_v3_results(results)

    # Auto-detect non-Latin and retry with multilingual
    if lang is None and _is_likely_non_latin(regions):
        return run_ocr(image, lang="multilingual")

    return regions
