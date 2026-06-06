"""Pipeline routing tests for non-passport documents (core/pipeline.py).

scan() is exercised end-to-end with preprocess() and run_ocr() stubbed, so the
document_classifier → extractor dispatch and the result shape are tested without
running real OCR.
"""

import numpy as np
import pytest

import core.pipeline as pipeline
from core.ocr_engine import TextRegion
from core.pipeline import DocumentScanResult, PanFields, scan
from core.preprocessor import PreprocessResult


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


def _pan_regions():
    return [
        _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
        _r("Permanent Account Number", 40, 90, 420, 115),
        _r("ABCPE1234F", 40, 120, 260, 152),
        _r("Name", 40, 170, 120, 195),
        _r("ROHIT SHARMA", 40, 198, 300, 230),
        _r("Father's Name", 40, 250, 260, 275),
        _r("MOHAN SHARMA", 40, 278, 320, 310),
        _r("Date of Birth", 40, 330, 220, 355),
        _r("15/08/1985", 40, 358, 220, 388),
    ]


@pytest.fixture
def stub_ocr(monkeypatch):
    """Stub preprocess + run_ocr so scan() routes deterministically."""
    image = np.zeros((1000, 800, 3), dtype=np.uint8)
    monkeypatch.setattr(pipeline, "preprocess", lambda _: PreprocessResult(image=image, warnings=[]))

    def _install(regions):
        monkeypatch.setattr(pipeline, "run_ocr", lambda img, **kw: list(regions))

    return _install


class TestRouting:
    def test_scan_routes_to_pan(self, stub_ocr):
        stub_ocr(_pan_regions())
        result = scan(b"fake")
        assert result.status == "success"
        assert result.document_type == "pan"
        assert result.page_type == "pan"
        assert result.pan_fields is not None
        assert result.pan_fields.pan_number == "ABCPE1234F"
        assert result.pan_fields.name == "ROHIT SHARMA"
        # Passport blocks stay empty for a PAN scan.
        assert result.fields is None
        assert result.back_page_fields is None

    def test_unknown_document_is_unsupported(self, stub_ocr):
        stub_ocr([_r("just a receipt", 40, 20, 300, 50), _r("total 100", 40, 60, 200, 90)])
        result = scan(b"fake")
        assert result.status == "unsupported_page"
        assert result.unsupported_reason == "UNSUPPORTED_DOCUMENT"


class TestResultShape:
    def test_to_dict_includes_all_document_blocks(self):
        result = DocumentScanResult(
            status="success",
            document_type="pan",
            page_type="pan",
            confidence=0.8,
            pan_fields=PanFields(pan_number="ABCPE1234F", name="ROHIT SHARMA"),
        )
        d = result.to_dict()
        # New block is camelCased and populated.
        assert d["panFields"]["panNumber"] == "ABCPE1234F"
        assert d["panFields"]["name"] == "ROHIT SHARMA"
        # Other document blocks present but null (additive, backward-compatible).
        assert d["aadhaarFields"] is None
        assert d["drivingLicenceFields"] is None
        assert d["voterIdFields"] is None
        # Passport contract keys remain.
        assert d["fields"] is None
        assert d["backPageFields"] is None
        assert "mrzValid" in d and "documentType" in d
