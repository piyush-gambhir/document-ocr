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

    def test_nested_voter_keyword_is_one_piece_of_evidence(self):
        cls = classify_document([_r("12 ELECTION COMMISSION ROAD")])

        assert cls.document_type == "voter_id"
        assert cls.reasons == ["VOTER_KEYWORDS_1"]
        assert cls.confidence == 0.74

    def test_nested_pan_keyword_is_one_piece_of_evidence(self):
        cls = classify_document([_r("INCOME TAX DEPARTMENT")])

        assert cls.document_type == "pan"
        assert cls.reasons == ["PAN_KEYWORDS_1"]
        assert cls.confidence == 0.74

    def test_nrega_job_card_with_explicit_scheme_title(self):
        regions = [
            _r("MAHATMA GANDHI NATIONAL RURAL EMPLOYMENT GUARANTEE ACT"),
            _r("JOB CARD", y1=60, y2=90),
            _r("UP-12-004-006-000123", y1=120, y2=150),
        ]
        cls = classify_document(regions)
        assert cls.document_type == "nrega_job_card"
        assert "NREGA_EXPLICIT_TITLE" in cls.reasons

    def test_nrega_job_card_with_rural_context(self):
        regions = [
            _r("JOB CARD"),
            _r("GRAM PANCHAYAT: RAMPUR", y1=60, y2=90),
            _r("HOUSEHOLD MEMBERS WILLING TO WORK", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "nrega_job_card"

    def test_nrega_title_wins_when_card_also_prints_valid_aadhaar(self):
        regions = [
            _r("MAHATMA GANDHI NREGA JOB CARD"),
            _r("Aadhaar No: 9998 8877 7669", y1=60, y2=90),
            _r("Gram Panchayat: Rampur", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "nrega_job_card"

    def test_bare_nrega_payment_reference_does_not_override_pan(self):
        regions = [
            _r("INCOME TAX DEPARTMENT"),
            _r("Permanent Account Number: ABCPE1234F", y1=60, y2=90),
            _r("NREGA PAYMENT ACCOUNT", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "pan"

    def test_nrega_hindi_title(self):
        regions = [
            _r("महात्मा गांधी राष्ट्रीय ग्रामीण रोजगार गारंटी अधिनियम"),
            _r("जॉब कार्ड", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "nrega_job_card"

    def test_npr_letter_with_full_title(self):
        regions = [
            _r("NATIONAL POPULATION REGISTER"),
            _r("Name of Resident: ASHA VERMA", y1=60, y2=90),
            _r("Address: NEW DELHI 110001", y1=120, y2=150),
        ]
        cls = classify_document(regions)
        assert cls.document_type == "npr_letter"
        assert "NPR_EXPLICIT_TITLE" in cls.reasons

    def test_npr_title_can_be_split_across_ocr_regions(self):
        regions = [
            _r("NATIONAL POPULATION"),
            _r("REGISTER", y1=60, y2=90),
            _r("Name of Resident: ASHA VERMA", y1=120, y2=150),
        ]
        assert classify_document(regions).document_type == "npr_letter"

    def test_npr_acronym_requires_issuer_context(self):
        regions = [
            _r("OFFICE OF THE REGISTRAR GENERAL & CENSUS COMMISSIONER"),
            _r("NPR NAME AND ADDRESS LETTER", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "npr_letter"

    def test_unknown_when_no_hints(self):
        regions = [_r("just some random text"), _r("with no document markers", y1=60, y2=90)]
        assert classify_document(regions).document_type == "unknown"

    def test_generic_job_card_is_not_nrega(self):
        regions = [
            _r("EMPLOYEE JOB CARD"),
            _r("Technician: replace air filter", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "unknown"

    def test_unrelated_npr_acronym_is_not_npr_letter(self):
        regions = [
            _r("NPR MEDIA SERVICES"),
            _r("Quarterly membership invoice", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "unknown"

    def test_pan_not_confused_with_voter(self):

        regions = [
            _r("INCOME TAX DEPARTMENT"),
            _r("ABCPE1234F", y1=60, y2=90),
        ]
        assert classify_document(regions).document_type == "pan"
