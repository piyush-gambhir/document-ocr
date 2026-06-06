"""Accuracy fixtures for the back-page extractor across passport-layout variants.

These complement test_back_page_extractor.py with additional realistic
TextRegion layouts targeting the historically weak spots called out in TODOS.md:
father / spouse names and multi-line address parsing across old and new Indian
passport generations. They feed TextRegion fixtures directly (no OCR), so they
are deterministic.
"""

from core.back_page_extractor import extract_back_page
from core.ocr_engine import TextRegion


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.97):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# ---------------------------------------------------------------------------
# Variant 1 — newer layout, "CITY - PINCODE STATECODE" on a single address line
# ---------------------------------------------------------------------------

def _new_layout_regions():
    return [
        _r("/ Name of Father / Legal Guardian", 70, 120, 470, 145),
        _r("ARVIND SINGH RATHORE", 60, 150, 360, 182),

        _r("/ Name of Mother", 70, 192, 300, 216),
        _r("SUNITA RATHORE", 60, 220, 300, 250),

        _r("/ Name of Spouse", 70, 258, 300, 284),
        _r("PRIYA RATHORE", 60, 285, 280, 316),

        _r("/ Address", 70, 324, 200, 350),
        _r("H.NO 42, SECTOR 5, SUSHANT LOK", 55, 350, 520, 388),
        _r("GURGAON - 122001 HR", 55, 400, 360, 436),

        _r("/ File No.", 70, 470, 210, 496),
        _r("HR1234567890123", 55, 500, 320, 532),
    ]


class TestNewLayoutAddressLine:
    def test_relatives_extracted(self):
        f = extract_back_page(_new_layout_regions())
        assert f.father_name == "ARVIND SINGH RATHORE"
        assert f.mother_name == "SUNITA RATHORE"
        assert f.spouse_name == "PRIYA RATHORE"

    def test_address_city_state_pincode(self):
        f = extract_back_page(_new_layout_regions())
        assert f.address is not None
        assert "SECTOR 5" in f.address
        assert f.pincode == "122001"
        assert f.city == "GURGAON"
        assert f.state == "Haryana"

    def test_file_number(self):
        f = extract_back_page(_new_layout_regions())
        assert f.file_number == "HR1234567890123"


# ---------------------------------------------------------------------------
# Variant 2 — unmarried holder: no spouse row at all
# ---------------------------------------------------------------------------

def _no_spouse_regions():
    return [
        _r("/ Name of Father / Legal Guardian", 70, 120, 470, 145),
        _r("RAMESH KUMAR", 60, 150, 300, 182),

        _r("/ Name of Mother", 70, 192, 300, 216),
        _r("KAVITA DEVI", 60, 220, 290, 250),

        _r("/ Address", 70, 300, 200, 326),
        _r("12 LAKE VIEW ROAD", 55, 328, 360, 362),
        _r("BANGALORE", 55, 372, 230, 404),
        _r("KARNATAKA 560001", 55, 412, 330, 444),
    ]


class TestNoSpouse:
    def test_spouse_is_none_when_absent(self):
        f = extract_back_page(_no_spouse_regions())
        assert f.spouse_name is None
        assert f.father_name == "RAMESH KUMAR"
        assert f.mother_name == "KAVITA DEVI"

    def test_full_state_name_and_city(self):
        f = extract_back_page(_no_spouse_regions())
        assert f.state == "Karnataka"
        assert f.pincode == "560001"
        # City is the locality line preceding the state line.
        assert f.city == "BANGALORE"
