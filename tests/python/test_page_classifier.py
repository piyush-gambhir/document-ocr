"""Tests for fast passport page classification."""

from core.ocr_engine import TextRegion
from core.page_classifier import classify_passport_page


def _make_region(text: str, y: int) -> TextRegion:
    return TextRegion(
        text=text,
        bbox=[[0, y], [300, y], [300, y + 20], [0, y + 20]],
        confidence=0.95,
    )


class TestPageClassifier:
    def test_classifies_biodata_page_from_mrz_and_labels(self):
        regions = [
            _make_region("SURNAME", 100),
            _make_region("DATE OF BIRTH", 140),
            _make_region("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", 400),
            _make_region("L898902C36UTO7408122F1204159ZE184226B<<<<<10", 440),
        ]

        result = classify_passport_page(regions)

        assert result.document_type == "passport"
        assert result.page_type == "passport_biodata"
        assert result.confidence >= 0.8

    def test_classifies_non_biodata_page_from_family_labels(self):
        regions = [
            _make_region("Name of Father / Legal Guardian", 100),
            _make_region("Address", 140),
            _make_region("File No.", 180),
        ]

        result = classify_passport_page(regions)

        assert result.document_type == "passport"
        assert result.page_type == "passport_non_biodata"
        assert result.confidence >= 0.7
