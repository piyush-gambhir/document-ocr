"""Tests for OCR result parsing (core/ocr_engine.py).

Does NOT import RapidOCR — only tests the parsing and detection utilities.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

import core.ocr_engine as ocr_engine
from core.ocr_engine import (
    OCRModelInitError,
    TextRegion,
    _get_ocr,
    _is_likely_non_latin,
    _parse_rapidocr_results,
)


class TestParseRapidOCRResults:
    def test_parse_normal(self):
        """Result with 2 boxes, 2 texts, 2 scores → 2 TextRegion objects."""
        result = MagicMock()
        result.boxes = np.array([
            [[0, 0], [100, 0], [100, 30], [0, 30]],
            [[0, 50], [100, 50], [100, 80], [0, 80]],
        ])
        result.txts = ("HELLO", "WORLD")
        result.scores = (0.95, 0.88)

        regions = _parse_rapidocr_results(result)
        assert len(regions) == 2
        assert regions[0].text == "HELLO"
        assert regions[0].confidence == 0.95
        assert regions[0].bbox == [[0, 0], [100, 0], [100, 30], [0, 30]]
        assert regions[1].text == "WORLD"
        assert regions[1].confidence == 0.88

    def test_parse_none_boxes(self):
        """None boxes → empty list."""
        result = MagicMock()
        result.boxes = None
        result.txts = None
        result.scores = None
        assert _parse_rapidocr_results(result) == []

    def test_parse_none_txts(self):
        """None txts → empty list."""
        result = MagicMock()
        result.boxes = np.array([[[0, 0], [10, 0], [10, 10], [0, 10]]])
        result.txts = None
        result.scores = (0.9,)
        assert _parse_rapidocr_results(result) == []

    def test_parse_skips_empty_text(self):
        """Empty/whitespace text should be skipped."""
        result = MagicMock()
        result.boxes = np.array([
            [[0, 0], [100, 0], [100, 30], [0, 30]],
            [[0, 50], [100, 50], [100, 80], [0, 80]],
        ])
        result.txts = ("HELLO", "  ")
        result.scores = (0.95, 0.88)

        regions = _parse_rapidocr_results(result)
        assert len(regions) == 1
        assert regions[0].text == "HELLO"

    def test_parse_single_result(self):
        """Single detection → single TextRegion."""
        result = MagicMock()
        result.boxes = np.array([[[5, 5], [50, 5], [50, 20], [5, 20]]])
        result.txts = ("SINGLE",)
        result.scores = (0.99,)

        regions = _parse_rapidocr_results(result)
        assert len(regions) == 1
        assert regions[0].text == "SINGLE"
        assert regions[0].confidence == 0.99
        assert regions[0].bbox == [[5, 5], [50, 5], [50, 20], [5, 20]]


@pytest.fixture
def clean_ocr_cache():
    """Snapshot and restore the singleton OCR instance cache around a test."""
    saved = dict(ocr_engine._ocr_instances)
    ocr_engine._ocr_instances.clear()
    try:
        yield
    finally:
        ocr_engine._ocr_instances.clear()
        ocr_engine._ocr_instances.update(saved)


class TestGetOCRModelInit:
    def test_raises_clear_error_on_model_init_failure(self, clean_ocr_cache, monkeypatch):
        """RapidOCR construction failing → OCRModelInitError(MODEL_INIT_FAILED)."""
        def boom(*args, **kwargs):
            raise RuntimeError("ModelScope unreachable")

        monkeypatch.setattr("rapidocr.RapidOCR", boom)

        with pytest.raises(OCRModelInitError) as exc_info:
            _get_ocr("en")
        assert "MODEL_INIT_FAILED" in str(exc_info.value)

    def test_failed_init_is_not_cached(self, clean_ocr_cache, monkeypatch):
        """A failed init must not poison the cache — a later call can retry."""
        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr("rapidocr.RapidOCR", boom)
        with pytest.raises(OCRModelInitError):
            _get_ocr("en")
        assert "en" not in ocr_engine._ocr_instances

        # Now the underlying problem is fixed — a retry succeeds and caches.
        sentinel = object()
        monkeypatch.setattr("rapidocr.RapidOCR", lambda *a, **k: sentinel)
        assert _get_ocr("en") is sentinel
        assert ocr_engine._ocr_instances["en"] is sentinel

    def test_returns_cached_instance_without_reconstructing(self, clean_ocr_cache):
        """If an instance is already cached, _get_ocr returns it directly."""
        sentinel = object()
        ocr_engine._ocr_instances["en"] = sentinel
        assert _get_ocr("en") is sentinel


class TestNonLatinDetection:
    def test_ascii_text_returns_false(self):
        """Pure ASCII text should not be detected as non-Latin."""
        regions = [
            TextRegion(text="HELLO WORLD", bbox=[], confidence=0.9),
            TextRegion(text="PASSPORT NUMBER", bbox=[], confidence=0.9),
        ]
        assert _is_likely_non_latin(regions) is False

    def test_devanagari_returns_true(self):
        """Text with >40% non-ASCII (Devanagari) should be detected as non-Latin."""
        regions = [
            TextRegion(text="\u092d\u093e\u0930\u0924 \u0917\u0923\u0930\u093e\u091c\u094d\u092f", bbox=[], confidence=0.9),
        ]
        assert _is_likely_non_latin(regions) is True

    def test_empty_returns_false(self):
        """Empty text should return False (no division by zero)."""
        regions = [TextRegion(text="", bbox=[], confidence=0.9)]
        assert _is_likely_non_latin(regions) is False


def test_line_recognition_leaves_cached_detector_enabled(clean_ocr_cache):
    model = MagicMock()
    model.use_det = True
    model.recognize_txt.return_value.txts = ('  EXAMPLE  ',)
    model.recognize_txt.return_value.scores = (.98,)
    ocr_engine._ocr_instances['en'] = model
    image = np.zeros((32, 400, 3), np.uint8)

    result = ocr_engine.run_line_ocr(image)
    assert result == [TextRegion('EXAMPLE', [[0, 0], [399, 0], [399, 31], [0, 31]], .98)]
    assert model.recognize_txt.call_args.args[0][0] is image
    model.assert_not_called()
    assert model.use_det is True

    # A later full-page request still uses the normal cached model path.
    model.return_value.boxes = None
    ocr_engine.run_ocr(image)
    model.assert_called_once_with(image)
    assert model.use_det is True


@pytest.mark.parametrize('texts,scores', [(None, None), ((), ()), (('   ',), (.98,))])
def test_empty_line_recognition_returns_no_regions(clean_ocr_cache, texts, scores):
    model = MagicMock()
    model.recognize_txt.return_value.txts = texts
    model.recognize_txt.return_value.scores = scores
    ocr_engine._ocr_instances['en'] = model
    assert ocr_engine.run_line_ocr(np.zeros((32, 400, 3), np.uint8)) == []
