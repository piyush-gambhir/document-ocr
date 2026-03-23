"""Tests for OCR result parsing (core/ocr_engine.py).

Does NOT import PaddleOCR — only tests the parsing and detection utilities.
"""

import pytest
import numpy as np

from core.ocr_engine import _parse_v3_results, TextRegion, _is_likely_non_latin


class TestParseV3Results:
    def test_parse_normal(self):
        """Dict with 2 texts, 2 scores, 2 polys → 2 TextRegion objects."""
        data = {
            "rec_texts": ["HELLO", "WORLD"],
            "rec_scores": [0.95, 0.88],
            "dt_polys": [
                [[0, 0], [100, 0], [100, 30], [0, 30]],
                [[0, 50], [100, 50], [100, 80], [0, 80]],
            ],
        }
        regions = _parse_v3_results([data])
        assert len(regions) == 2
        assert regions[0].text == "HELLO"
        assert regions[0].confidence == 0.95
        assert regions[0].bbox == [[0, 0], [100, 0], [100, 30], [0, 30]]
        assert regions[1].text == "WORLD"
        assert regions[1].confidence == 0.88

    def test_parse_empty_none(self):
        """None input → empty list."""
        assert _parse_v3_results(None) == []

    def test_parse_empty_dict(self):
        """Empty dict → empty list (no rec_texts key)."""
        assert _parse_v3_results({}) == []

    def test_parse_empty_list(self):
        """Empty list → empty list."""
        assert _parse_v3_results([]) == []

    def test_parse_missing_bbox(self):
        """Dict with texts and scores but no dt_polys → TextRegions with empty bbox."""
        data = {
            "rec_texts": ["HELLO", "WORLD"],
            "rec_scores": [0.95, 0.88],
        }
        regions = _parse_v3_results([data])
        assert len(regions) == 2
        assert regions[0].bbox == []
        assert regions[1].bbox == []

    def test_parse_numpy_polys(self):
        """Numpy array polys should be converted via .tolist() path."""
        poly1 = np.array([[10, 20], [110, 20], [110, 50], [10, 50]])
        poly2 = np.array([[10, 60], [110, 60], [110, 90], [10, 90]])
        data = {
            "rec_texts": ["FOO", "BAR"],
            "rec_scores": [0.90, 0.85],
            "dt_polys": [poly1, poly2],
        }
        regions = _parse_v3_results([data])
        assert len(regions) == 2
        assert regions[0].bbox == [[10, 20], [110, 20], [110, 50], [10, 50]]
        assert isinstance(regions[0].bbox[0][0], int)

    def test_parse_single_dict(self):
        """Unwrapped dict (not in list) → should wrap and parse."""
        data = {
            "rec_texts": ["SINGLE"],
            "rec_scores": [0.99],
            "dt_polys": [[[5, 5], [50, 5], [50, 20], [5, 20]]],
        }
        regions = _parse_v3_results(data)
        assert len(regions) == 1
        assert regions[0].text == "SINGLE"
        assert regions[0].confidence == 0.99


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
