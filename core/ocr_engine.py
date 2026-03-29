"""
RapidOCR wrapper. Accepts a preprocessed image, returns detected text regions.

Uses PP-OCRv5 models via ONNX Runtime — no PaddlePaddle dependency.
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
# Singleton OCR instance
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_ocr_instances: dict[str, object] = {}


def _get_ocr(lang: str = "en"):
    """Get or create a cached RapidOCR instance."""
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    # Map string language codes to RapidOCR Enum values
    _lang_map = {
        "en": LangRec.EN,
        "latin": LangRec.LATIN,
        "ch": LangRec.CH,
        "chinese_cht": LangRec.CHINESE_CHT,
        "japan": LangRec.JAPAN,
        "korean": LangRec.KOREAN,
        "arabic": LangRec.ARABIC,
        "cyrillic": LangRec.CYRILLIC,
        "devanagari": LangRec.DEVANAGARI,
        "ka": LangRec.KA,
        "ta": LangRec.TA,
        "te": LangRec.TE,
    }

    if lang not in _ocr_instances:
        with _lock:
            if lang not in _ocr_instances:
                rec_lang = _lang_map.get(lang, LangRec.EN)
                _ocr_instances[lang] = RapidOCR(params={
                    "Global.use_cls": False,
                    "Det.model_type": ModelType.MOBILE,
                    "Det.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.lang_type": rec_lang,
                    "Rec.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                })
    return _ocr_instances[lang]


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _parse_rapidocr_results(result) -> list[TextRegion]:
    """Parse RapidOCR output into TextRegion list."""
    regions: list[TextRegion] = []

    if result.boxes is None or result.txts is None:
        return regions

    for box, txt, score in zip(result.boxes, result.txts, result.scores):
        text = str(txt).strip()
        if text:
            bbox = [[int(pt[0]), int(pt[1])] for pt in box]
            regions.append(TextRegion(text=text, bbox=bbox, confidence=float(score)))

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
              'latin' if non-Latin script is detected.

    Returns:
        List of TextRegion with text, bounding box, and confidence.
    """
    use_lang = lang or "en"
    ocr = _get_ocr(use_lang)

    result = ocr(image)
    regions = _parse_rapidocr_results(result)

    # Auto-detect non-Latin and retry with multilingual
    if lang is None and _is_likely_non_latin(regions):
        return run_ocr(image, lang="latin")

    return regions
