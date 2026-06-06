"""Tests for the Driving Licence extractor (core/driving_licence_extractor.py).

Deterministic fixtures only — no real OCR. Each ``TextRegion`` is positioned
with ``_r(text, x1, y1, x2, y2)`` so the spatial label/value helpers behave as
they would on a real card.
"""

from core.driving_licence_extractor import (
    DrivingLicenceFields,
    extract_driving_licence,
)
from core.ocr_engine import TextRegion


def _bbox(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _r(text, x1, y1, x2, y2, conf=0.95):
    return TextRegion(text=text, bbox=_bbox(x1, y1, x2, y2), confidence=conf)


# ---------------------------------------------------------------------------
# Standard value-right (Maharashtra-style) layout
# ---------------------------------------------------------------------------

def _dl_regions():
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
        _r("Address :", 40, 270, 170, 295),
        _r("14 NEHRU NAGAR, PUNE", 40, 300, 400, 328),
        _r("MAHARASHTRA 411001", 40, 332, 360, 360),
    ]


class TestStandardLayout:
    def test_dl_number_and_name(self):
        f = extract_driving_licence(_dl_regions())
        assert f.dl_number == "MH1220110012345"
        assert f.name == "VIKRAM PATEL"

    def test_dates_disambiguated_by_label(self):
        f = extract_driving_licence(_dl_regions())
        assert f.date_of_birth == "09/03/1986"
        assert f.issue_date == "12/06/2015"
        assert f.validity_date == "11/06/2035"

    def test_address_collected(self):
        f = extract_driving_licence(_dl_regions())
        assert f.address is not None
        assert "NEHRU NAGAR" in f.address
        assert "MAHARASHTRA 411001" in f.address

    def test_returns_dataclass_with_all_fields(self):
        f = extract_driving_licence(_dl_regions())
        assert isinstance(f, DrivingLicenceFields)
        # Contract fields exist.
        for name in (
            "dl_number",
            "name",
            "date_of_birth",
            "issue_date",
            "validity_date",
            "address",
        ):
            assert hasattr(f, name)


# ---------------------------------------------------------------------------
# DL number format variants (spaced / hyphenated / split across regions)
# ---------------------------------------------------------------------------

class TestDlNumberVariants:
    def test_spaced_form(self):
        regions = [
            _r("DL No", 40, 70, 150, 95),
            _r("MH12 20110012345", 170, 70, 470, 95),
        ]
        assert extract_driving_licence(regions).dl_number == "MH1220110012345"

    def test_hyphenated_form(self):
        regions = [
            _r("Licence No", 40, 70, 200, 95),
            _r("DL-0420110149646", 220, 70, 520, 95),
        ]
        assert extract_driving_licence(regions).dl_number == "DL0420110149646"

    def test_tn_compact_form(self):
        regions = [_r("TN0120200001234", 40, 70, 320, 95)]
        assert extract_driving_licence(regions).dl_number == "TN0120200001234"

    def test_hr_spaced_form(self):
        regions = [_r("HR06 19850034761", 40, 70, 360, 95)]
        assert extract_driving_licence(regions).dl_number == "HR0619850034761"

    def test_number_split_across_two_regions(self):
        # OCR sometimes splits the state/RTO prefix from the serial.
        regions = [
            _r("DL No", 40, 70, 150, 95),
            _r("MH12", 170, 70, 250, 95),
            _r("20110012345", 260, 70, 470, 95),
        ]
        assert extract_driving_licence(regions).dl_number == "MH1220110012345"

    def test_no_number_present(self):
        regions = [_r("DRIVING LICENCE", 40, 20, 320, 50)]
        assert extract_driving_licence(regions).dl_number is None


# ---------------------------------------------------------------------------
# Three-date disambiguation: order on the card must not matter
# ---------------------------------------------------------------------------

class TestDateDisambiguation:
    def test_assigns_each_date_by_adjacent_label(self):
        f = extract_driving_licence(_dl_regions())
        assert f.date_of_birth == "09/03/1986"
        assert f.issue_date == "12/06/2015"
        assert f.validity_date == "11/06/2035"

    def test_reordered_dates_still_correct(self):
        # Same labels/values but laid out in a scrambled vertical order.
        regions = [
            _r("Valid Till", 40, 70, 180, 95),
            _r("11/06/2035", 220, 70, 400, 95),
            _r("Date of Birth", 40, 110, 230, 135),
            _r("09/03/1986", 260, 110, 430, 135),
            _r("Date of Issue", 40, 150, 230, 175),
            _r("12/06/2015", 260, 150, 430, 175),
        ]
        f = extract_driving_licence(regions)
        assert f.date_of_birth == "09/03/1986"
        assert f.issue_date == "12/06/2015"
        assert f.validity_date == "11/06/2035"

    def test_dob_value_below_label(self):
        regions = [
            _r("DOB", 40, 70, 110, 95),
            _r("09/03/1986", 40, 100, 210, 125),
            _r("DOI", 40, 150, 110, 175),
            _r("12/06/2015", 40, 180, 210, 205),
        ]
        f = extract_driving_licence(regions)
        assert f.date_of_birth == "09/03/1986"
        assert f.issue_date == "12/06/2015"

    def test_dot_separated_dates(self):
        regions = [
            _r("Date of Birth", 40, 70, 230, 95),
            _r("09.03.1986", 260, 70, 430, 95),
        ]
        assert extract_driving_licence(regions).date_of_birth == "09.03.1986"


# ---------------------------------------------------------------------------
# Two validity dates: NT (non-transport) vs TR (transport)
# ---------------------------------------------------------------------------

class TestTwoValidityDates:
    def _nt_tr_regions(self):
        return [
            _r("Date of Issue", 40, 70, 230, 95),
            _r("12/06/2015", 260, 70, 430, 95),
            _r("Validity (NT)", 40, 110, 230, 135),
            _r("11/06/2035", 260, 110, 430, 135),
            _r("Validity (TR)", 40, 150, 230, 175),
            _r("11/06/2018", 260, 150, 430, 175),
        ]

    def test_primary_validity_is_non_transport(self):
        f = extract_driving_licence(self._nt_tr_regions())
        # NT (non-transport) is the primary validity_date.
        assert f.validity_date == "11/06/2035"

    def test_transport_validity_exposed_separately(self):
        f = extract_driving_licence(self._nt_tr_regions())
        assert f.validity_date_transport == "11/06/2018"

    def test_issue_date_not_confused_with_validity(self):
        f = extract_driving_licence(self._nt_tr_regions())
        assert f.issue_date == "12/06/2015"

    def test_only_transport_validity_falls_back_to_primary(self):
        regions = [
            _r("Validity (TR)", 40, 70, 230, 95),
            _r("11/06/2018", 260, 70, 430, 95),
        ]
        f = extract_driving_licence(regions)
        # When only a TR date exists, still surface it as validity_date.
        assert f.validity_date == "11/06/2018"
        assert f.validity_date_transport == "11/06/2018"


# ---------------------------------------------------------------------------
# Multi-line / present-vs-permanent address
# ---------------------------------------------------------------------------

class TestAddress:
    def test_multi_line_address(self):
        regions = [
            _r("Address", 40, 270, 170, 295),
            _r("14 NEHRU NAGAR", 40, 300, 300, 328),
            _r("KOTHRUD, PUNE", 40, 332, 300, 360),
            _r("MAHARASHTRA 411038", 40, 364, 330, 392),
        ]
        f = extract_driving_licence(regions)
        assert "14 NEHRU NAGAR" in f.address
        assert "KOTHRUD, PUNE" in f.address
        assert "MAHARASHTRA 411038" in f.address

    def test_present_preferred_over_permanent(self):
        regions = [
            _r("Permanent Address", 40, 270, 260, 295),
            _r("OLD VILLAGE HOUSE, BIHAR", 40, 300, 380, 328),
            _r("Present Address", 460, 270, 660, 295),
            _r("12 MG ROAD, BENGALURU", 460, 300, 800, 328),
        ]
        f = extract_driving_licence(regions)
        assert "MG ROAD" in f.address
        assert "BIHAR" not in f.address

    def test_address_stops_at_next_label(self):
        regions = [
            _r("Address", 40, 270, 170, 295),
            _r("14 NEHRU NAGAR, PUNE", 40, 300, 400, 328),
            _r("Blood Group", 40, 340, 200, 365),
            _r("B+", 220, 340, 280, 365),
        ]
        f = extract_driving_licence(regions)
        assert "NEHRU NAGAR" in f.address
        # The next label/value must not leak into the address block.
        assert "Blood Group" not in f.address
        assert "B+" not in f.address


# ---------------------------------------------------------------------------
# Relation (S/D/W of) — must not be confused with the holder name
# ---------------------------------------------------------------------------

class TestRelation:
    def test_relation_and_name_distinct(self):
        regions = [
            _r("Name", 40, 70, 130, 95),
            _r("VIKRAM PATEL", 150, 70, 380, 95),
            _r("S/D/W of", 40, 110, 180, 135),
            _r("RAMESH PATEL", 200, 110, 430, 135),
        ]
        f = extract_driving_licence(regions)
        assert f.name == "VIKRAM PATEL"
        assert f.relation_name == "RAMESH PATEL"

    def test_son_of_label(self):
        regions = [
            _r("Son of", 40, 110, 150, 135),
            _r("RAMESH PATEL", 170, 110, 400, 135),
        ]
        assert extract_driving_licence(regions).relation_name == "RAMESH PATEL"


# ---------------------------------------------------------------------------
# Blood group
# ---------------------------------------------------------------------------

class TestBloodGroup:
    def test_positive_compact(self):
        regions = [
            _r("Blood Group", 40, 70, 200, 95),
            _r("B+", 220, 70, 280, 95),
        ]
        assert extract_driving_licence(regions).blood_group == "B+"

    def test_negative_with_ve_suffix(self):
        regions = [
            _r("Blood Group", 40, 70, 200, 95),
            _r("O-VE", 220, 70, 320, 95),
        ]
        assert extract_driving_licence(regions).blood_group == "O-"

    def test_ab_positive(self):
        regions = [
            _r("BG", 40, 70, 90, 95),
            _r("AB+", 110, 70, 190, 95),
        ]
        assert extract_driving_licence(regions).blood_group == "AB+"

    def test_no_blood_group(self):
        regions = [_r("Name", 40, 70, 130, 95), _r("VIKRAM", 150, 70, 300, 95)]
        assert extract_driving_licence(regions).blood_group is None


# ---------------------------------------------------------------------------
# Class of vehicle (COV)
# ---------------------------------------------------------------------------

class TestClassOfVehicle:
    def test_single_cov_via_label(self):
        regions = [
            _r("Class of Vehicle", 40, 70, 260, 95),
            _r("LMV", 280, 70, 360, 95),
        ]
        assert extract_driving_licence(regions).class_of_vehicle == "LMV"

    def test_multiple_cov_tokens(self):
        regions = [
            _r("COV", 40, 70, 110, 95),
            _r("MCWG LMV", 130, 70, 360, 95),
        ]
        cov = extract_driving_licence(regions).class_of_vehicle
        assert "MCWG" in cov
        assert "LMV" in cov

    def test_cov_fallback_scan(self):
        # No COV label, but canonical tokens appear on the card.
        regions = [
            _r("DRIVING LICENCE", 40, 20, 320, 50),
            _r("MCWG", 40, 400, 140, 425),
            _r("LMV", 160, 400, 240, 425),
        ]
        cov = extract_driving_licence(regions).class_of_vehicle
        assert "MCWG" in cov
        assert "LMV" in cov

    def test_no_cov(self):
        regions = [_r("Name", 40, 70, 130, 95), _r("VIKRAM PATEL", 150, 70, 380, 95)]
        assert extract_driving_licence(regions).class_of_vehicle is None


# ---------------------------------------------------------------------------
# Full card with every field present
# ---------------------------------------------------------------------------

class TestFullCard:
    def _full_regions(self):
        return [
            _r("DRIVING LICENCE", 40, 20, 360, 50),
            _r("DL No", 40, 70, 150, 95),
            _r("MH12 20110012345", 170, 70, 480, 95),
            _r("Name", 40, 110, 130, 135),
            _r("VIKRAM PATEL", 150, 110, 380, 135),
            _r("S/D/W of", 40, 150, 180, 175),
            _r("RAMESH PATEL", 200, 150, 430, 175),
            _r("Date of Birth", 40, 190, 230, 215),
            _r("09/03/1986", 260, 190, 430, 215),
            _r("Blood Group", 480, 190, 660, 215),
            _r("B+", 680, 190, 740, 215),
            _r("Date of Issue", 40, 230, 230, 255),
            _r("12/06/2015", 260, 230, 430, 255),
            _r("Class of Vehicle", 480, 230, 700, 255),
            _r("MCWG LMV", 720, 230, 900, 255),
            _r("Validity (NT)", 40, 270, 230, 295),
            _r("11/06/2035", 260, 270, 430, 295),
            _r("Validity (TR)", 40, 310, 230, 335),
            _r("11/06/2018", 260, 310, 430, 335),
            _r("Present Address", 40, 350, 260, 375),
            _r("14 NEHRU NAGAR, KOTHRUD", 40, 380, 400, 408),
            _r("PUNE MAHARASHTRA 411038", 40, 412, 400, 440),
        ]

    def test_all_fields_extracted(self):
        f = extract_driving_licence(self._full_regions())
        assert f.dl_number == "MH1220110012345"
        assert f.name == "VIKRAM PATEL"
        assert f.relation_name == "RAMESH PATEL"
        assert f.date_of_birth == "09/03/1986"
        assert f.issue_date == "12/06/2015"
        assert f.validity_date == "11/06/2035"
        assert f.validity_date_transport == "11/06/2018"
        assert f.blood_group == "B+"
        assert "MCWG" in f.class_of_vehicle
        assert "LMV" in f.class_of_vehicle
        assert "NEHRU NAGAR" in f.address
        assert "411038" in f.address


# ---------------------------------------------------------------------------
# Robustness / empty input
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_empty_regions(self):
        f = extract_driving_licence([])
        assert f.dl_number is None
        assert f.name is None
        assert f.date_of_birth is None
        assert f.address is None

    def test_no_crash_on_label_only(self):
        regions = [
            _r("DL No", 40, 70, 150, 95),
            _r("Name", 40, 110, 130, 135),
            _r("Address", 40, 150, 170, 175),
        ]
        f = extract_driving_licence(regions)
        assert f.dl_number is None
        assert f.name is None
