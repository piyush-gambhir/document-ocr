"""Tests for the Aadhaar extractor (core/aadhaar_extractor.py).

Fixtures feed TextRegion objects directly into extract_aadhaar — no real OCR.
The 12-digit number 9998 8877 7669 is Verhoeff-valid (confirmed via
core.validators.is_valid_aadhaar), so checksum_valid is True wherever it
appears as the full Aadhaar number.
"""

from core.aadhaar_extractor import AadhaarFields, extract_aadhaar
from core.ocr_engine import TextRegion
from core.validators import is_valid_aadhaar


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# A known-valid Aadhaar number used across fixtures.
VALID_AADHAAR = "9998 8877 7669"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _aadhaar_front():
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("ANJALI VERMA", 120, 120, 360, 150),
        _r("DOB : 14/07/1994", 120, 160, 360, 188),
        _r("Female", 120, 196, 240, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
    ]


def _aadhaar_front_yob():
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("SURESH KUMAR", 120, 120, 360, 150),
        _r("Year of Birth : 1988", 120, 160, 380, 188),
        _r("Male", 120, 196, 240, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
    ]


def _aadhaar_front_hindi_gender():
    """Bilingual front: Hindi header, Hindi/English DOB label, Hindi gender."""
    return [
        _r("भारत सरकार", 120, 10, 360, 40),
        _r("Government of India", 120, 44, 480, 74),
        _r("PRIYA SHARMA", 120, 120, 360, 150),
        _r("जन्म तिथि / DOB : 02/03/1990", 120, 160, 460, 188),
        _r("महिला / FEMALE", 120, 196, 320, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
    ]


def _aadhaar_front_hindi_only_gender():
    """Gender printed only in Devanagari (no Latin gender word)."""
    return [
        _r("भारत सरकार", 120, 10, 360, 40),
        _r("RAVI TEJA", 120, 120, 360, 150),
        _r("DOB: 11/11/1985", 120, 160, 360, 188),
        _r("पुरुष", 120, 196, 220, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
    ]


def _aadhaar_back():
    return [
        _r("Address:", 60, 60, 200, 88),
        _r("S/O RAMESH VERMA, 24 GANDHI ROAD", 60, 96, 560, 124),
        _r("ANDHERI WEST, MUMBAI", 60, 132, 420, 160),
        _r("MAHARASHTRA - 400058", 60, 168, 400, 196),
        _r("9998 8877 7669", 60, 240, 320, 272),
    ]


def _aadhaar_back_hindi_noise():
    """Back page with a Devanagari label and Devanagari noise lines mixed in."""
    return [
        _r("पता / Address:", 60, 60, 260, 88),
        _r("पता का हिंदी पाठ", 60, 96, 360, 124),  # Devanagari-only noise
        _r("C/O SUNITA DEVI, 12 NEHRU MARG", 60, 130, 560, 158),
        _r("सेक्टर 5", 60, 166, 220, 194),  # Devanagari-only noise
        _r("JAIPUR, RAJASTHAN 302001", 60, 200, 460, 228),
        _r("9998 8877 7669", 60, 290, 320, 322),
    ]


def _aadhaar_front_with_vid():
    """Front that also prints a 16-digit VID, which must NOT be the Aadhaar."""
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("MEENA IYER", 120, 120, 360, 150),
        _r("DOB : 09/09/1992", 120, 160, 360, 188),
        _r("Female", 120, 196, 240, 224),
        _r("9998 8877 7669", 120, 260, 380, 292),
        _r("VID : 9148 6541 8231 2156", 120, 300, 520, 332),
    ]


def _aadhaar_front_vid_before_number():
    """VID listed before the Aadhaar — the naive matcher would grab the VID."""
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("KARAN MEHTA", 120, 120, 360, 150),
        _r("DOB : 21/06/1991", 120, 160, 360, 188),
        _r("Male", 120, 196, 240, 224),
        _r("VID 9148 6541 8231 2156", 120, 250, 520, 282),
        _r("9998 8877 7669", 120, 300, 380, 332),
    ]


def _aadhaar_masked():
    """Masked Aadhaar download: only the last 4 digits are visible."""
    return [
        _r("Government of India", 120, 20, 480, 50),
        _r("DEEPA NAIR", 120, 120, 360, 150),
        _r("DOB : 30/12/1980", 120, 160, 360, 188),
        _r("Female", 120, 196, 240, 224),
        _r("XXXX XXXX 9012", 120, 260, 380, 292),
    ]


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------

class TestFixtureSanity:
    def test_fixture_number_is_verhoeff_valid(self):
        assert is_valid_aadhaar(VALID_AADHAAR) is True

    def test_empty_input_does_not_crash(self):
        f = extract_aadhaar([])
        assert isinstance(f, AadhaarFields)
        assert f.aadhaar_number is None
        assert f.checksum_valid is False
        assert f.name is None


# ---------------------------------------------------------------------------
# Front page
# ---------------------------------------------------------------------------

class TestAadhaarFront:
    def test_number_name_dob_gender(self):
        f = extract_aadhaar(_aadhaar_front())
        assert f.aadhaar_number == "9998 8877 7669"
        assert f.checksum_valid is True
        assert f.name == "ANJALI VERMA"
        assert f.date_of_birth == "14/07/1994"
        assert f.year_of_birth is None
        assert f.gender == "FEMALE"
        assert f.aadhaar_last4 == "7669"
        assert f.aadhaar_masked is False

    def test_year_of_birth_variant(self):
        f = extract_aadhaar(_aadhaar_front_yob())
        assert f.year_of_birth == "1988"
        assert f.date_of_birth is None
        assert f.gender == "MALE"
        assert f.name == "SURESH KUMAR"
        assert f.checksum_valid is True

    def test_bilingual_hindi_gender_and_dob_label(self):
        f = extract_aadhaar(_aadhaar_front_hindi_gender())
        assert f.name == "PRIYA SHARMA"
        assert f.date_of_birth == "02/03/1990"
        assert f.gender == "FEMALE"
        assert f.aadhaar_number == "9998 8877 7669"

    def test_devanagari_only_gender_normalized(self):
        f = extract_aadhaar(_aadhaar_front_hindi_only_gender())
        assert f.gender == "MALE"
        assert f.name == "RAVI TEJA"
        assert f.date_of_birth == "11/11/1985"

    def test_name_is_line_directly_above_dob(self):
        """The header band must be skipped; the name is the line above DOB."""
        f = extract_aadhaar(_aadhaar_front())
        assert f.name == "ANJALI VERMA"
        assert f.name != "Government of India"

    def test_name_above_dob_with_multiple_candidate_lines(self):
        """Two name-like lines exist; the one just above DOB wins."""
        regions = [
            _r("Government of India", 120, 20, 480, 50),
            _r("UNITED COLOURS", 120, 70, 360, 100),  # decoy line, higher up
            _r("ROHIT BANSAL", 120, 120, 360, 150),    # real name, above DOB
            _r("DOB : 05/05/1995", 120, 160, 360, 188),
            _r("Male", 120, 196, 240, 224),
            _r("9998 8877 7669", 120, 260, 380, 292),
        ]
        f = extract_aadhaar(regions)
        assert f.name == "ROHIT BANSAL"


# ---------------------------------------------------------------------------
# VID handling
# ---------------------------------------------------------------------------

class TestVidIsolation:
    def test_vid_after_number_not_picked(self):
        f = extract_aadhaar(_aadhaar_front_with_vid())
        assert f.aadhaar_number == "9998 8877 7669"
        assert f.checksum_valid is True
        assert f.vid == "9148 6541 8231 2156"

    def test_vid_before_number_not_picked(self):
        """Regression: naive 4-4-4 matching would slice the VID's first 12
        digits ('9148 6541 8231'). Masking the 16-digit VID prevents that."""
        f = extract_aadhaar(_aadhaar_front_vid_before_number())
        assert f.aadhaar_number == "9998 8877 7669"
        assert f.checksum_valid is True
        # The VID's leading 12 digits must never be the Aadhaar number.
        assert f.aadhaar_number != "9148 6541 8231"
        assert f.vid == "9148 6541 8231 2156"

    def test_only_vid_present_yields_no_aadhaar(self):
        regions = [
            _r("Government of India", 120, 20, 480, 50),
            _r("VID : 9148 6541 8231 2156", 120, 300, 520, 332),
        ]
        f = extract_aadhaar(regions)
        assert f.aadhaar_number is None
        assert f.checksum_valid is False
        assert f.vid == "9148 6541 8231 2156"


# ---------------------------------------------------------------------------
# Masked Aadhaar
# ---------------------------------------------------------------------------

class TestMaskedAadhaar:
    def test_masked_number_does_not_crash_and_flags_partial(self):
        f = extract_aadhaar(_aadhaar_masked())
        assert f.aadhaar_number is None
        assert f.checksum_valid is False
        assert f.aadhaar_masked is True
        assert f.aadhaar_last4 == "9012"
        # Other fields still extracted from a masked card.
        assert f.name == "DEEPA NAIR"
        assert f.date_of_birth == "30/12/1980"
        assert f.gender == "FEMALE"


# ---------------------------------------------------------------------------
# Back page
# ---------------------------------------------------------------------------

class TestAadhaarBack:
    def test_address_and_pincode(self):
        f = extract_aadhaar(_aadhaar_back())
        assert f.address is not None
        assert "GANDHI ROAD" in f.address
        assert f.pincode == "400058"
        assert f.aadhaar_number == "9998 8877 7669"

    def test_back_with_hindi_label_and_noise_lines(self):
        f = extract_aadhaar(_aadhaar_back_hindi_noise())
        assert f.address is not None
        # Real Latin address lines are present.
        assert "NEHRU MARG" in f.address
        assert "JAIPUR" in f.address
        # Devanagari-only noise lines are excluded.
        assert "हिंदी" not in f.address
        assert "सेक्टर" not in f.address
        # Pincode parsed from the address block.
        assert f.pincode == "302001"

    def test_back_page_does_not_fabricate_a_name(self):
        """A back/address page has no holder name; the extractor must not
        promote a C/O line or a locality line into the name field."""
        f = extract_aadhaar(_aadhaar_back())
        assert f.name is None

    def test_standalone_number_line_excluded_from_address(self):
        """The Aadhaar number printed below the address block must not be
        glued onto the address string."""
        f = extract_aadhaar(_aadhaar_back())
        assert f.address is not None
        assert "9998 8877 7669" not in f.address
        assert "GANDHI ROAD" in f.address


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

class TestResilience:
    def test_number_with_extra_ocr_spacing(self):
        """OCR may split/space the number oddly; the grouped form still parses."""
        regions = [
            _r("Government of India", 120, 20, 480, 50),
            _r("AMIT SINGH", 120, 120, 360, 150),
            _r("DOB : 01/01/2000", 120, 160, 360, 188),
            _r("Male", 120, 196, 240, 224),
            _r("9998 8877 7669", 120, 260, 380, 292),
        ]
        f = extract_aadhaar(regions)
        assert f.aadhaar_number == "9998 8877 7669"
        assert f.checksum_valid is True

    def test_front_without_dob_falls_back_to_topmost_name(self):
        """No DOB line: the name falls back to the topmost name-like line."""
        regions = [
            _r("Government of India", 120, 20, 480, 50),
            _r("NISHA RAO", 120, 120, 360, 150),
            _r("Female", 120, 196, 240, 224),
            _r("9998 8877 7669", 120, 260, 380, 292),
        ]
        f = extract_aadhaar(regions)
        assert f.name == "NISHA RAO"
        assert f.gender == "FEMALE"
        assert f.date_of_birth is None
        assert f.year_of_birth is None

    def test_aadhaar_fields_default_construction(self):
        f = AadhaarFields()
        assert f.aadhaar_number is None
        assert f.checksum_valid is False
        assert f.aadhaar_masked is False
        assert f.vid is None
