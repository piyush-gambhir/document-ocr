"""Tests for the bilingual back-page field extractor."""

from core.back_page_extractor import _extract_old_passport_row, extract_back_page
from core.ocr_engine import TextRegion


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=1.0):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# ---------------------------------------------------------------------------
# Indian-passport-style fixture: bilingual labels + 3-column Old Passport row
# ---------------------------------------------------------------------------

def _indian_back_page_regions():
    return [
        # Father (bilingual label split into two regions on same row, value below)
        _r("fe /", 76, 123, 309, 148, conf=0.55),
        _r("of Father / Legal Guardian", 374, 126, 581, 151, conf=0.98),
        _r("SHRADHANAND MEHTA", 60, 152, 343, 184),

        # Mother
        _r("/ Name of Mother", 71, 193, 308, 217, conf=0.88),
        _r("RANJANA MEHTA", 56, 219, 278, 249),

        # Spouse
        _r("y/ Name of Spouse", 70, 258, 366, 286, conf=0.77),
        _r("NEHA MEHTA", 53, 283, 229, 320, conf=0.99),

        # Address
        _r("qem / Address", 67, 324, 183, 350, conf=0.87),
        _r("WZ-14/3,STREET NO.18,KRISHNA PARK EXTN.", 49, 347, 699, 391, conf=0.98),
        _r("NEW MAHAVIR NAGAR,DELHI", 51, 409, 436, 448),
        _r("PIN:110018,DELHI,INDIA", 51, 470, 424, 510),

        # Old passport row: bilingual prefix + compound English label, then
        # 3 columnar values.
        _r("god qeaie  i ae ger on  a fa o", 68, 523, 451, 548, conf=0.55),
        _r("tard / Old Passport No. with Date and Place of Issua",
           439, 523, 869, 556, conf=0.92),
        _r("H0840323", 52, 543, 191, 576, conf=0.99),
        _r("13/10/2008", 286, 544, 458, 580),
        _r("DELHI", 617, 553, 705, 582),

        # File No. row (must NOT be absorbed into the address or old-passport row)
        _r("./ File No.", 67, 584, 210, 610, conf=0.89),
        _r("DL2072369058018", 52, 614, 304, 643),
    ]


class TestIndianBackPageExtraction:
    def test_extracts_relatives_through_bilingual_labels(self):
        fields = extract_back_page(_indian_back_page_regions())
        assert fields.father_name == "SHRADHANAND MEHTA"
        assert fields.mother_name == "RANJANA MEHTA"
        assert fields.spouse_name == "NEHA MEHTA"

    def test_address_excludes_hindi_label_noise_and_stops_at_old_passport_row(self):
        fields = extract_back_page(_indian_back_page_regions())
        assert fields.address is not None
        # Each real address line is present
        assert "WZ-14/3" in fields.address
        assert "NEW MAHAVIR NAGAR" in fields.address
        assert "PIN:110018" in fields.address
        # Hindi-script noise text from the next row must NOT bleed in
        assert "god qeaie" not in fields.address.lower()
        # The Old Passport row's values must NOT be glued onto the address
        assert "H0840323" not in fields.address
        assert "13/10/2008" not in fields.address
        # Pincode parsed from the address block
        assert fields.pincode == "110018"

    def test_extracts_old_passport_row_three_columns(self):
        fields = extract_back_page(_indian_back_page_regions())
        # Without the 3-column extractor, the file number's "L2072369"
        # substring would leak into old_passport_number.
        assert fields.old_passport_number == "H0840323"
        assert fields.old_passport_date_of_issue == "13/10/2008"
        assert fields.old_passport_place_of_issue == "DELHI"

    def test_extracts_file_number(self):
        fields = extract_back_page(_indian_back_page_regions())
        assert fields.file_number == "DL2072369058018"

    def test_extracts_state_and_city_from_comma_tokenized_address(self):
        fields = extract_back_page(_indian_back_page_regions())
        assert fields.state == "Delhi"
        # The token immediately preceding the state is the locality / city.
        assert fields.city == "NEW MAHAVIR NAGAR"


class TestOldPassportRowExtractor:
    def test_classifies_three_columns_by_content_shape(self):
        regions = _indian_back_page_regions()
        label = next(r for r in regions if "Old Passport" in r.text)
        pp_no, doi, poi = _extract_old_passport_row(regions, label)
        assert pp_no == "H0840323"
        assert doi == "13/10/2008"
        assert poi == "DELHI"

    def test_does_not_misclassify_file_number_as_passport_number(self):
        """Critical: re.search would slice 'L2072369' out of 'DL2072369058018'.
        re.fullmatch must require an exact 8-char passport-number shape."""
        # Simplified row containing only a file-number-shaped value below the
        # compound label — should produce no passport number, not a slice.
        regions = [
            _r("Old Passport No. with Date and Place of Issue",
               400, 100, 900, 130, conf=0.9),
            _r("DL2072369058018", 50, 140, 300, 170),
        ]
        label = regions[0]
        pp_no, doi, poi = _extract_old_passport_row(regions, label)
        assert pp_no is None  # do NOT slice "L2072369"
        assert doi is None
        assert poi is None

    def test_returns_none_for_no_renewal_row(self):
        """If there's nothing under the label, all three values are None."""
        regions = [
            _r("Old Passport No. with Date and Place of Issue",
               400, 100, 900, 130, conf=0.9),
        ]
        pp_no, doi, poi = _extract_old_passport_row(regions, regions[0])
        assert pp_no is None
        assert doi is None
        assert poi is None
