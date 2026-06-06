"""Tests for the PAN card extractor (core/pan_extractor.py).

Fixtures feed ``TextRegion`` objects directly into ``extract_pan`` — no real
OCR — so the suite is deterministic. Bounding boxes use the standard 4-point
order [TL, TR, BR, BL] in pixels.
"""

from core.ocr_engine import TextRegion
from core.pan_extractor import PanFields, extract_pan


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pan_card_value_below():
    """Older NSDL PAN layout: bilingual labels above values."""
    return [
        _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
        _r("GOVT. OF INDIA", 40, 52, 240, 78),
        _r("Name", 40, 90, 120, 115),
        _r("ROHIT SHARMA", 40, 118, 300, 150),
        _r("Father's Name", 40, 160, 260, 185),
        _r("MOHAN SHARMA", 40, 188, 320, 220),
        _r("Date of Birth", 40, 230, 220, 255),
        _r("15/08/1985", 40, 258, 220, 288),
        _r("Permanent Account Number", 40, 300, 420, 325),
        _r("ABCPE1234F", 40, 330, 260, 362),
    ]


def _pan_card_value_right():
    """Newer e-PAN layout: 'Label : value' on one row."""
    return [
        _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
        _r("Name :", 40, 90, 140, 115),
        _r("PRIYA NAIR", 160, 90, 360, 115),
        _r("Father's Name :", 40, 130, 240, 155),
        _r("RAJAN NAIR", 260, 130, 460, 155),
        _r("DOB :", 40, 170, 110, 195),
        _r("02/11/1992", 130, 170, 320, 195),
        _r("ABCPK5678Q", 40, 220, 260, 252),
    ]


def _epan_parents_name_label():
    """e-PAN that uses 'Parent's Name' and 'Name of the Cardholder'."""
    return [
        _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
        _r("Name of the Cardholder :", 40, 90, 320, 115),
        _r("ANANYA IYER", 340, 90, 540, 115),
        _r("Parent's Name :", 40, 130, 240, 155),
        _r("SURESH IYER", 260, 130, 470, 155),
        _r("Date of Birth :", 40, 170, 230, 195),
        _r("23-04-1990", 250, 170, 440, 195),
        _r("FGHPI9012K", 40, 220, 260, 252),
    ]


def _bilingual_noisy_value_below():
    """Old card with Hindi-script noise riding on the same row as each English
    label, plus a noisy government header."""
    return [
        _r("भारत सरकार", 40, 8, 180, 32, conf=0.4),
        _r("INCOME TAX DEPARTMENT", 200, 10, 560, 40),
        _r("नाम / Name", 40, 90, 240, 116, conf=0.6),
        _r("VIKRAM SINGH", 40, 120, 300, 152),
        _r("पिता का नाम / Father's Name", 40, 162, 360, 190, conf=0.55),
        _r("HARPAL SINGH", 40, 194, 320, 226),
        _r("जन्म की तारीख / Date of Birth", 40, 234, 380, 262, conf=0.5),
        _r("07/12/1978", 40, 266, 230, 296),
        _r("स्थायी लेखा संख्या", 40, 306, 240, 332, conf=0.45),
        _r("Permanent Account Number", 40, 334, 420, 360),
        _r("LMNPS4567R", 40, 364, 270, 396),
    ]


def _missing_name_labels():
    """No Name / Father's Name labels at all — only a DOB label and the PAN.
    Name resolution should yield nothing rather than guessing."""
    return [
        _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
        _r("Date of Birth", 40, 90, 220, 115),
        _r("11/01/2000", 40, 118, 230, 148),
        _r("QWXPA8888B", 40, 180, 270, 212),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPanExtractor:
    def test_value_below_layout(self):
        f = extract_pan(_pan_card_value_below())
        assert f.pan_number == "ABCPE1234F"
        assert f.name == "ROHIT SHARMA"
        assert f.father_name == "MOHAN SHARMA"
        assert f.date_of_birth == "15/08/1985"

    def test_value_right_layout(self):
        f = extract_pan(_pan_card_value_right())
        assert f.pan_number == "ABCPK5678Q"
        assert f.name == "PRIYA NAIR"
        assert f.father_name == "RAJAN NAIR"
        assert f.date_of_birth == "02/11/1992"

    def test_parents_name_and_cardholder_labels(self):
        f = extract_pan(_epan_parents_name_label())
        assert f.pan_number == "FGHPI9012K"
        assert f.name == "ANANYA IYER"
        assert f.father_name == "SURESH IYER"
        assert f.date_of_birth == "23-04-1990"

    def test_bilingual_noisy_layout(self):
        f = extract_pan(_bilingual_noisy_value_below())
        assert f.pan_number == "LMNPS4567R"
        assert f.name == "VIKRAM SINGH"
        assert f.father_name == "HARPAL SINGH"
        assert f.date_of_birth == "07/12/1978"

    # --- name vs father disambiguation ------------------------------------

    def test_name_not_confused_with_father_name_value_below(self):
        f = extract_pan(_pan_card_value_below())
        assert f.name == "ROHIT SHARMA"
        assert f.father_name == "MOHAN SHARMA"
        assert f.name != f.father_name

    def test_name_not_confused_with_father_name_value_right(self):
        f = extract_pan(_pan_card_value_right())
        assert f.name == "PRIYA NAIR"
        assert f.father_name == "RAJAN NAIR"
        assert f.name != f.father_name

    def test_name_dropped_when_only_father_label_present(self):
        """No standalone 'Name' label, only 'Father's Name'. The plain-name
        lookup must NOT latch onto the father's value via the substring match."""
        regions = [
            _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
            _r("Father's Name", 40, 90, 260, 115),
            _r("MOHAN SHARMA", 40, 118, 320, 150),
            _r("Date of Birth", 40, 160, 220, 185),
            _r("15/08/1985", 40, 188, 220, 218),
            _r("ABCPE1234F", 40, 250, 260, 282),
        ]
        f = extract_pan(regions)
        assert f.father_name == "MOHAN SHARMA"
        assert f.name is None

    # --- DOB format variants ----------------------------------------------

    def test_dob_slash_format(self):
        f = extract_pan(_pan_card_value_below())
        assert f.date_of_birth == "15/08/1985"

    def test_dob_dash_format(self):
        f = extract_pan(_epan_parents_name_label())
        assert f.date_of_birth == "23-04-1990"

    def test_dob_is_printed_string_not_iso(self):
        """DOB is preserved as printed (no ISO normalisation)."""
        f = extract_pan(_pan_card_value_right())
        assert f.date_of_birth == "02/11/1992"
        assert "-" not in f.date_of_birth or f.date_of_birth.count("-") == 2

    def test_dob_prefers_date_near_label_over_stray_date(self):
        """A stray date elsewhere on the card must not win over the DOB-labelled
        date."""
        regions = [
            _r("Date of Birth", 40, 200, 220, 225),
            _r("15/08/1985", 40, 228, 220, 258),
            # A printed 'issued on' style date placed visually first.
            _r("Issued 01/01/2024", 40, 60, 320, 90),
            _r("Name", 40, 100, 120, 125),
            _r("ROHIT SHARMA", 40, 128, 300, 158),
            _r("ABCPE1234F", 40, 300, 260, 332),
        ]
        f = extract_pan(regions)
        assert f.date_of_birth == "15/08/1985"

    # --- PAN number robustness --------------------------------------------

    def test_pan_not_confused_with_date(self):
        f = extract_pan(_pan_card_value_below())
        assert f.pan_number == "ABCPE1234F"

    def test_pan_not_sliced_from_dl_number(self):
        """A 15-char DL-shaped token must not be sliced into a fake PAN, and the
        real PAN should still be found."""
        regions = [
            _r("INCOME TAX DEPARTMENT", 40, 20, 400, 50),
            _r("DL2072369058018", 40, 90, 300, 115),  # DL shape, not a PAN
            _r("ABCPE1234F", 40, 130, 260, 162),
        ]
        f = extract_pan(regions)
        assert f.pan_number == "ABCPE1234F"

    def test_pan_prefers_holder_type_valid_token(self):
        """When two PAN-shaped tokens exist, the one with a valid holder-type
        4th character wins over a shaped-but-invalid one."""
        regions = [
            # 4th char 'Z' is not a valid holder type -> shaped but invalid.
            _r("ABCZE1234F", 40, 90, 260, 122),
            # 4th char 'P' (individual) -> valid.
            _r("WXYPK5678Q", 40, 140, 260, 172),
        ]
        f = extract_pan(regions)
        assert f.pan_number == "WXYPK5678Q"

    def test_pan_from_noisy_region_with_spaces(self):
        """OCR sometimes splits the PAN with spaces; normalize_pan compacts it."""
        regions = [
            _r("Permanent Account Number", 40, 60, 420, 90),
            _r("ABCP E123 4F", 40, 94, 260, 126),
        ]
        f = extract_pan(regions)
        assert f.pan_number == "ABCPE1234F"

    def test_pan_shaped_fallback_when_none_valid(self):
        """If no token has a valid holder type, fall back to the shaped token."""
        regions = [
            _r("ABCZE1234F", 40, 90, 260, 122),  # 'Z' invalid holder type
        ]
        f = extract_pan(regions)
        assert f.pan_number == "ABCZE1234F"

    # --- missing labels / partial cards -----------------------------------

    def test_missing_name_and_father_labels(self):
        f = extract_pan(_missing_name_labels())
        assert f.pan_number == "QWXPA8888B"
        assert f.date_of_birth == "11/01/2000"
        assert f.name is None
        assert f.father_name is None

    def test_empty_regions_returns_all_none(self):
        f = extract_pan([])
        assert f == PanFields()
        assert f.pan_number is None
        assert f.name is None
        assert f.father_name is None
        assert f.date_of_birth is None

    def test_no_date_anywhere_yields_none_dob(self):
        regions = [
            _r("Name", 40, 90, 120, 115),
            _r("ROHIT SHARMA", 40, 118, 300, 150),
            _r("ABCPE1234F", 40, 180, 260, 212),
        ]
        f = extract_pan(regions)
        assert f.date_of_birth is None
        assert f.name == "ROHIT SHARMA"
        assert f.pan_number == "ABCPE1234F"

    def test_no_pan_anywhere_yields_none(self):
        regions = [
            _r("Name", 40, 90, 120, 115),
            _r("ROHIT SHARMA", 40, 118, 300, 150),
            _r("Date of Birth", 40, 160, 220, 185),
            _r("15/08/1985", 40, 188, 220, 218),
        ]
        f = extract_pan(regions)
        assert f.pan_number is None
        assert f.name == "ROHIT SHARMA"
        assert f.date_of_birth == "15/08/1985"

    # --- contract -----------------------------------------------------------

    def test_panfields_contract_field_names(self):
        """The four contract fields must exist with these exact names."""
        f = extract_pan([])
        for name in ("pan_number", "name", "father_name", "date_of_birth"):
            assert hasattr(f, name)
