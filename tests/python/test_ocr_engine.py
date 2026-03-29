"""Tests for OCR result parsing (core/ocr_engine.py).

Does NOT import RapidOCR — only tests the parsing and detection utilities.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

from core.ocr_engine import _parse_rapidocr_results, TextRegion, _is_likely_non_latin


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
