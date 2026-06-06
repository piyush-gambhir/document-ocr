"""Tests for the document-type router (core/document_classifier.py)."""

from core.document_classifier import classify_document
from core.ocr_engine import TextRegion


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1=40, y1=20, x2=400, y2=50, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


class TestClassifyDocument:
    def test_pan_card(self):
        regions = [
            _r("INCOME TAX DEPARTMENT"),
            _r("GOVT. OF INDIA", y1=60, y2=90),
            _r("Permanent Account Number", y1=100, y2=130),
            _r("ABCPE1234F", y1=140, y2=170),
        ]
        assert classify_document(regions).document_type == "pan"

    def test_aadhaar_card(self):
        regions = [
            _r("Government of India"),
            _r("Unique Identification Authority of India", y1=60, y2=90),
            _r("9998 8877 7669", y1=200, y2=230),
            _r("AADHAAR", y1=240, y2=270),
        ]
        cls = classify_document(regions)
        assert cls.document_type == "aadhaar"
        assert "AADHAAR_CHECKSUM_VALID" in cls.reasons

    def test_driving_licence(self):
        regions = [
            _r("DRIVING LICENCE"),
            _r("THE UNION OF INDIA", y1=60, y2=90),
            _r("MH1220110012345", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "driving_licence"

    def test_voter_id(self):
        regions = [
            _r("ELECTION COMMISSION OF INDIA"),
            _r("ELECTOR PHOTO IDENTITY CARD", y1=60, y2=90),
            _r("ABC1234567", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "voter_id"

    def test_unknown_when_no_hints(self):
        regions = [_r("just some random text"), _r("with no document markers", y1=60, y2=90)]
        assert classify_document(regions).document_type == "unknown"

    def test_pan_not_confused_with_voter(self):
        # A PAN token must not be mistaken for an EPIC and vice-versa.
        regions = [
            _r("INCOME TAX DEPARTMENT"),
            _r("ABCPE1234F", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "pan"
