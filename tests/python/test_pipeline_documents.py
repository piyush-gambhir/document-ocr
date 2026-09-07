"""Pipeline routing tests for non-passport documents (core/pipeline.py).

scan() is exercised end-to-end with preprocess() and run_ocr() stubbed, so the
document_classifier → extractor dispatch and the result shape are tested without
running real OCR.
"""

import numpy as np
import pytest

import core.pipeline as pipeline
from core.ocr_engine import TextRegion
from core.nrega_extractor import NregaFields, NregaMember
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


def _aadhaar_regions():
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("ANJALI VERMA", 120, 120, 360, 150),
        _r("DOB : 14/07/1994", 120, 160, 360, 188),
        _r("Female", 120, 196, 240, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
    ]


def _driving_licence_regions():
    return [
        _r("DRIVING LICENCE", 40, 20, 320, 50),
        _r("DL No :", 40, 70, 150, 95),
        _r("MH1220110012345", 170, 70, 460, 95),
        _r("Name :", 40, 110, 130, 135),
        _r("VIKRAM PATEL", 150, 110, 380, 135),
        _r("Date of Birth :", 40, 150, 230, 175),
        _r("09/03/1986", 250, 150, 420, 175),
        _r("Date of Issue :", 40, 190, 230, 215),
        _r("12/06/2015", 250, 190, 420, 215),
        _r("Valid Till :", 40, 230, 180, 255),
        _r("11/06/2035", 200, 230, 380, 255),
    ]


def _voter_id_regions():
    return [
        _r("ELECTION COMMISSION OF INDIA", 40, 20, 460, 50),
        _r("ABC1234567", 360, 60, 560, 90),
        _r("Elector's Name :", 40, 110, 260, 135),
        _r("DEEPAK MEHTA", 280, 110, 500, 135),
        _r("Date of Birth :", 40, 230, 230, 255),
        _r("21/12/1990", 250, 230, 420, 255),
    ]


def _back_style_voter_id_regions():
    return [
        _r("ELECTION COMMISSION OF INDIA", 40, 20, 460, 50),
        _r("ABC1234567", 360, 60, 560, 90),
        _r("Elector's Name :", 40, 110, 260, 135),
        _r("DEEPAK MEHTA", 280, 110, 500, 135),
        _r("Name of Father :", 40, 150, 260, 175),
        _r("SURESH MEHTA", 280, 150, 500, 175),
        _r("Address :", 40, 190, 150, 215),
        _r("SYNTHETIC ADDRESS", 180, 190, 430, 215),
        _r("Date of Birth :", 40, 230, 230, 255),
        _r("21/12/1990", 250, 230, 420, 255),
    ]


def _passport_back_with_voter_words_in_address():
    return [
        _r("Name of Father", 40, 30, 230, 56),
        _r("RAMESH KUMAR", 270, 30, 480, 56),
        _r("Address", 40, 90, 150, 116),
        _r(
            "12 ELECTION COMMISSION ROAD NEW DELHI",
            180,
            90,
            690,
            116,
        ),
        _r("File No", 40, 150, 150, 176),
        _r("SYNTHETIC/FILE/001", 180, 150, 450, 176),
    ]


def _nrega_regions():
    return [
        _r("MAHATMA GANDHI NREGA", 20, 10, 370, 40),
        _r("Job Card No.", 20, 60, 170, 86),
        _r("RJ-27-001-002-0008147/00", 190, 60, 510, 86),
        _r("Name of Head of Household", 20, 145, 280, 171),
        _r("SITA DEVI", 310, 145, 460, 171),
        _r("Gram Panchayat", 20, 320, 180, 346),
        _r("Rampur", 210, 320, 320, 346),
    ]


def _npr_regions():
    return [
        _r("OFFICE OF THE REGISTRAR GENERAL, INDIA", 40, 20, 620, 50),
        _r("NATIONAL POPULATION REGISTER", 120, 60, 540, 92),
        _r("Reference No: NPR/DL/2024/004217", 40, 120, 560, 148),
        _r("Name of Resident: ASHA VERMA", 40, 165, 500, 193),
        _r(
            "Address of Resident: 14, LAKE VIEW ROAD, NEW DELHI 110019",
            40,
            210,
            760,
            238,
        ),
        _r("Date of Issue: 14/03/2024", 40, 260, 420, 288),
    ]


@pytest.fixture
def stub_ocr(monkeypatch):
    """Stub preprocess + run_ocr so scan() routes deterministically."""
    image = np.zeros((1000, 800, 3), dtype=np.uint8)
    monkeypatch.setattr(
        pipeline,
        "preprocess",
        lambda _: PreprocessResult(image=image, warnings=[]),
    )

    def _install(regions, *, kyc_regions=None):
        monkeypatch.setattr(pipeline, "run_ocr", lambda img, **kw: list(regions))
        monkeypatch.setattr(
            pipeline,
            "run_kyc_ocr",
            lambda img, **kw: list(
                regions if kyc_regions is None else kyc_regions
            ),
        )

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
        assert result.probe_text == []
        # Passport blocks stay empty for a PAN scan.
        assert result.fields is None
        assert result.back_page_fields is None

    @pytest.mark.parametrize(
        ("regions", "document_type", "result_attribute", "identifier_attribute"),
        [
            (_aadhaar_regions(), "aadhaar", "aadhaar_fields", "aadhaar_number"),
            (_voter_id_regions(), "voter_id", "voter_id_fields", "epic_number"),
            (
                _nrega_regions(),
                "nrega_job_card",
                "nrega_job_card_fields",
                "job_card_number",
            ),
        ],
    )
    def test_scan_routes_to_validated_identifier_documents(
        self,
        stub_ocr,
        regions,
        document_type,
        result_attribute,
        identifier_attribute,
    ):
        stub_ocr(regions)
        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == document_type
        assert result.page_type == document_type
        assert result.identifier_valid is True
        assert result.missing_required_fields == []
        assert getattr(getattr(result, result_attribute), identifier_attribute)

    def test_additional_language_recovers_licence_when_english_probe_is_unknown(
        self,
        stub_ocr,
        monkeypatch,
    ):
        monkeypatch.setenv("DOCUMENT_OCR_KYC_LANGS", "en,devanagari")
        stub_ocr(
            [_r("MH1220110012345", 40, 20, 340, 50)],
            kyc_regions=_driving_licence_regions(),
        )

        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "driving_licence"
        assert result.driving_licence_fields is not None
        assert (
            result.driving_licence_fields.dl_number
            == "MH1220110012345"
        )

    def test_scan_routes_to_npr_letter_without_authenticity_claim(self, stub_ocr):
        stub_ocr(_npr_regions())
        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "npr_letter"
        assert result.npr_letter_fields is not None
        assert result.npr_letter_fields.name == "ASHA VERMA"
        assert result.identifier_valid is None
        assert "IDENTIFIER_NOT_OFFLINE_VERIFIABLE" in result.warnings

    def test_npr_title_without_labelled_personal_fields_fails_closed(
        self,
        stub_ocr,
    ):
        stub_ocr(
            [
                _r(
                    "NATIONAL POPULATION REGISTER NAME AND ADDRESS LETTER",
                    40,
                    20,
                    680,
                    50,
                ),
                _r("Dear Citizen", 40, 70, 240, 98),
                _r(
                    "This is a routine informational notice",
                    40,
                    110,
                    540,
                    138,
                ),
                _r("Please retain this letter", 40, 150, 390, 178),
            ]
        )

        result = scan(b"fake")

        assert result.status == "failure"
        assert result.document_type == "npr_letter"
        assert result.missing_required_fields == ["name", "address"]

    def test_explicit_voter_identity_wins_over_generic_passport_back_labels(
        self,
        stub_ocr,
        monkeypatch,
    ):
        regions = _back_style_voter_id_regions()
        assert (
            pipeline.classify_passport_page(regions).page_type
            == "passport_non_biodata"
        )
        stub_ocr(regions)
        monkeypatch.setattr(
            pipeline,
            "run_kyc_ocr",
            lambda *_args, **_kwargs: pytest.fail(
                "A strongly identified card should reuse the complete OCR read"
            ),
        )
        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "voter_id"
        assert result.page_type == "voter_id"
        assert result.voter_id_fields.epic_number == "ABC1234567"

    def test_voter_words_in_passport_address_do_not_replace_passport(
        self,
        stub_ocr,
    ):
        regions = _passport_back_with_voter_words_in_address()
        assert (
            pipeline.classify_passport_page(regions).page_type
            == "passport_non_biodata"
        )
        stub_ocr(regions)

        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "passport"
        assert result.page_type == "passport_non_biodata"
        assert result.back_page_fields is not None

    def test_no_mrz_passport_reuses_one_default_full_page_ocr(
        self,
        monkeypatch,
    ):
        image = np.zeros((1000, 800, 3), dtype=np.uint8)
        targeted_regions = [
            _r("Surname", 40, 100, 180, 130),
            _r("Given Name", 40, 150, 210, 180),
        ]
        full_regions = [
            _r("PASSPORT", 40, 20, 220, 50),
            *targeted_regions,
        ]
        calls = {"default_full_page": 0}

        monkeypatch.setattr(
            pipeline,
            "preprocess",
            lambda _: PreprocessResult(image=image, warnings=[]),
        )
        monkeypatch.setattr(
            pipeline,
            "_extract_targeted_regions",
            lambda _: targeted_regions,
        )
        def _default_full_page_ocr(_image, **_kwargs):
            calls["default_full_page"] += 1
            return full_regions

        monkeypatch.setattr(pipeline, "run_ocr", _default_full_page_ocr)
        monkeypatch.setattr(
            pipeline,
            "run_kyc_ocr",
            lambda *_args, **_kwargs: pytest.fail(
                "KYC routing must not run after a positive passport probe"
            ),
        )

        result = scan(b"fake")

        assert result.document_type == "passport"
        assert calls == {"default_full_page": 1}

    def test_explicit_driving_licence_wins_over_generic_biodata_labels(
        self,
        stub_ocr,
        monkeypatch,
    ):
        stub_ocr(_driving_licence_regions())
        monkeypatch.setattr(
            pipeline,
            "run_kyc_ocr",
            lambda *_args, **_kwargs: pytest.fail(
                "A strongly identified licence should reuse the complete OCR read"
            ),
        )
        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "driving_licence"
        assert result.driving_licence_fields.dl_number == "MH1220110012345"

    def test_full_page_kyc_ocr_is_reachable_when_bottom_probe_is_empty(
        self, monkeypatch
    ):
        monkeypatch.setenv("DOCUMENT_OCR_KYC_LANGS", "en,devanagari")
        image = np.zeros((1000, 800, 3), dtype=np.uint8)
        monkeypatch.setattr(
            pipeline,
            "preprocess",
            lambda _: PreprocessResult(image=image, warnings=[]),
        )
        monkeypatch.setattr(pipeline, "run_ocr", lambda img, **kw: [])
        monkeypatch.setattr(
            pipeline,
            "run_kyc_ocr",
            lambda img, **kw: _npr_regions(),
        )

        result = scan(b"fake")

        assert result.status == "success"
        assert result.document_type == "npr_letter"

    def test_partial_known_document_fails_closed(self, stub_ocr):
        stub_ocr(
            [
                _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
                _r("Permanent Account Number", 40, 90, 420, 115),
                _r("ABCPE1234F", 40, 120, 260, 152),
            ]
        )
        result = scan(b"fake")

        assert result.status == "failure"
        assert result.document_type == "pan"
        assert result.confidence <= 0.69
        assert result.missing_required_fields == ["name", "dateOfBirth"]
        assert "MISSING_REQUIRED_FIELDS" in result.errors

    def test_low_confidence_required_values_are_not_extracted(
        self,
        stub_ocr,
    ):
        stub_ocr(
            [
                _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
                _r("Permanent Account Number", 40, 90, 420, 115),
                _r("ABCPE1234F", 40, 120, 260, 152, conf=0.0),
                _r("Name", 40, 170, 120, 195),
                _r("ROHIT SHARMA", 40, 198, 300, 230, conf=0.0),
                _r("Date of Birth", 40, 330, 220, 355),
                _r("15/08/1985", 40, 358, 220, 388, conf=0.0),
                _r("unrelated high confidence text", 40, 420, 400, 450),
            ]
        )

        result = scan(b"fake")

        assert result.status == "failure"
        assert result.document_type == "pan"
        assert result.pan_fields is not None
        assert result.pan_fields.pan_number is None
        assert "MISSING_REQUIRED_FIELDS" in result.errors

    def test_unknown_document_is_unsupported(self, stub_ocr):
        stub_ocr([_r("just a receipt", 40, 20, 300, 50), _r("total 100", 40, 60, 200, 90)])
        result = scan(b"fake")
        assert result.status == "unsupported_page"
        assert result.unsupported_reason == "UNSUPPORTED_DOCUMENT"
        assert result.probe_text == []


class TestResultShape:
    def test_to_dict_includes_all_document_blocks(self):
        result = DocumentScanResult(
            status="success",
            document_type="pan",
            page_type="pan",
            confidence=0.8,
            pan_fields=PanFields(pan_number="ABCPE1234F", name="ROHIT SHARMA"),
            nrega_job_card_fields=NregaFields(
                job_card_number="RJ-27-001-002-0008147/00",
                members=[NregaMember(serial_number="1", name="SITA DEVI", age=39)],
            ),
        )
        d = result.to_dict()
        # New block is camelCased and populated.
        assert d["panFields"]["panNumber"] == "ABCPE1234F"
        assert d["panFields"]["name"] == "ROHIT SHARMA"
        # Other document blocks present but null (additive, backward-compatible).
        assert d["aadhaarFields"] is None
        assert d["drivingLicenceFields"] is None
        assert d["voterIdFields"] is None
        assert d["nregaJobCardFields"]["jobCardNumber"] == (
            "RJ-27-001-002-0008147/00"
        )
        assert d["nregaJobCardFields"]["members"] == [
            {
                "serialNumber": "1",
                "name": "SITA DEVI",
                "fatherOrHusbandName": None,
                "gender": None,
                "age": 39,
            }
        ]
        assert d["nprLetterFields"] is None
        # Passport contract keys remain.
        assert d["fields"] is None
        assert d["backPageFields"] is None
        assert "mrzValid" in d and "documentType" in d
        assert d["identifierValid"] is None
        assert d["missingRequiredFields"] == []
