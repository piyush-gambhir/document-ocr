"""Tests for cross-validation and confidence scoring (core/validator.py)."""

import pytest

from core.validator import (
    find_label_row_left_edge,
    find_visual_field,
    find_visual_value_near,
    validate,
    ValidationResult,
)
from core.mrz_parser import MRZResult, MRZField
from core.ocr_engine import TextRegion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mrz(
    *,
    surname="SMITH",
    given_names="JOHN",
    passport_number="AB1234567",
    nationality="GBR",
    country_code="GBR",
    dob="1990-03-15",
    sex="M",
    expiry="2030-01-01",
    pn_valid=True,
    dob_valid=True,
    expiry_valid=True,
    overall_valid=True,
) -> MRZResult:
    """Build a mock MRZResult with controllable checksum validity."""
    return MRZResult(
        document_type=MRZField(value="P", raw="P<"),
        country_code=MRZField(value=country_code, raw=country_code),
        surname=MRZField(value=surname, raw=surname),
        given_names=MRZField(value=given_names, raw=given_names),
        passport_number=MRZField(value=passport_number, raw=passport_number, checksum_valid=pn_valid),
        nationality=MRZField(value=nationality, raw=nationality),
        date_of_birth=MRZField(value=dob, raw="900315", checksum_valid=dob_valid),
        sex=MRZField(value=sex, raw=sex),
        expiry_date=MRZField(value=expiry, raw="300101", checksum_valid=expiry_valid),
        personal_number=MRZField(value=None, raw="<<<<<<<<<<<<<<", checksum_valid=True),
        overall_checksum_valid=overall_valid,
        raw_lines=(
            "P<GBRSMITH<<JOHN<<<<<<<<<<<<<<<<<<<<<<<<<<<",
            "AB12345671GBR9003151M3001011<<<<<<<<<<<<<<0",
        ),
    )


def _make_regions(label_text, value_text, label_y=100, value_y=150, x=50, conf=0.95):
    """Build label + value TextRegion pair spatially arranged."""
    return [
        TextRegion(
            text=label_text,
            bbox=[[x, label_y], [x + 200, label_y], [x + 200, label_y + 30], [x, label_y + 30]],
            confidence=conf,
        ),
        TextRegion(
            text=value_text,
            bbox=[[x, value_y], [x + 200, value_y], [x + 200, value_y + 30], [x, value_y + 30]],
            confidence=conf,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_mrz_none_gives_low_score(self):
        """No MRZ detected → mrz_score=0, cross_score defaults to 0.5, ocr_conf=0."""
        result = validate(mrz=None, regions=[])
        # confidence = 0*0.4 + 0.5*0.3 + 0*0.3 = 0.15
        assert result.confidence == 0.15
        assert "MRZ_NOT_DETECTED" in result.errors

    def test_mrz_all_checksums_valid(self):
        """Fully valid MRZ → mrz_score = 1.0."""
        mrz = _make_mrz(overall_valid=True)
        regions = _make_regions("SURNAME", "SMITH") + _make_regions("DATE OF BIRTH", "1990-03-15", label_y=200, value_y=250)
        result = validate(mrz=mrz, regions=regions)
        # mrz_score = 1.0 since overall_valid is True
        assert result.confidence > 0.5

    def test_mrz_partial_checksums(self):
        """Overall checksum fails but 2/3 individual pass → partial mrz_score."""
        mrz = _make_mrz(
            overall_valid=False,
            pn_valid=True,
            dob_valid=True,
            expiry_valid=False,
        )
        result = validate(mrz=mrz, regions=[])
        # mrz_score = (2/3)*0.7 ≈ 0.4667
        # cross_score = 0.5 (no cross-match data), ocr_conf = 0.0
        expected_mrz_score = (2 / 3) * 0.7
        expected_confidence = round(expected_mrz_score * 0.4 + 0.5 * 0.3 + 0.0 * 0.3, 3)
        assert result.confidence == expected_confidence

    def test_cross_match_name_fuzzy(self):
        """Visual name matches MRZ surname → no NAME_MISMATCH warning."""
        mrz = _make_mrz(surname="SMITH")
        regions = _make_regions("SURNAME", "SMITH")
        result = validate(mrz=mrz, regions=regions)
        assert "NAME_MISMATCH" not in result.warnings

    def test_cross_match_name_mismatch(self):
        """Visual name differs from MRZ surname → NAME_MISMATCH warning."""
        mrz = _make_mrz(surname="SMITH")
        regions = _make_regions("SURNAME", "JOHNSON")
        result = validate(mrz=mrz, regions=regions)
        assert "NAME_MISMATCH" in result.warnings

    def test_cross_match_name_ignores_given_name_label(self):
        """Surname matching should not get confused by a nearby given-name label."""
        mrz = _make_mrz(surname="RAMADUGULA", given_names="SITA MAHA LAKSHMI")
        regions = (
            _make_regions("Given Name()", "SITA MAHA LAKSHMI", label_y=100, value_y=150)
            + _make_regions("SURNAME", "RAMADUGULA", label_y=220, value_y=270)
        )
        result = validate(mrz=mrz, regions=regions)
        assert "NAME_MISMATCH" not in result.warnings

    def test_value_lookup_prefers_value_over_following_label(self):
        """The nearest region below a label is sometimes another label, not the value."""
        regions = [
            TextRegion(
                text="SURNAME",
                bbox=[[50, 100], [250, 100], [250, 130], [50, 130]],
                confidence=0.95,
            ),
            TextRegion(
                text="Given Name()",
                bbox=[[50, 140], [250, 140], [250, 170], [50, 170]],
                confidence=0.95,
            ),
            TextRegion(
                text="RAMADUGULA",
                bbox=[[50, 175], [250, 175], [250, 205], [50, 205]],
                confidence=0.99,
            ),
        ]
        label = find_visual_field(regions, ["SURNAME"])
        value = find_visual_value_near(regions, label)
        assert value is not None
        assert value.text == "RAMADUGULA"

    def test_value_lookup_allows_small_vertical_overlap(self):
        """Passport labels and values can overlap by a few pixels in OCR boxes."""
        regions = [
            TextRegion(
                text="SURNAME",
                bbox=[[50, 100], [250, 100], [250, 130], [50, 130]],
                confidence=0.95,
            ),
            TextRegion(
                text="RAMADUGULA",
                bbox=[[50, 128], [250, 128], [250, 158], [50, 158]],
                confidence=0.99,
            ),
        ]
        label = find_visual_field(regions, ["SURNAME"])
        value = find_visual_value_near(regions, label)
        assert value is not None
        assert value.text == "RAMADUGULA"

    def test_value_lookup_handles_bilingual_label_prefix(self):
        """Indian / Arabic / Cyrillic labels OCR as two regions on the same row.
        The English region's left edge is *not* aligned with the value column —
        the value column matches the leftmost edge of the bilingual block."""
        regions = [
            # Bilingual prefix (mostly noise) at the left
            TextRegion(
                text="fe /",
                bbox=[[60, 120], [200, 120], [200, 150], [60, 150]],
                confidence=0.55,
            ),
            # English label well to the right of the prefix
            TextRegion(
                text="Name of Father / Legal Guardian",
                bbox=[[370, 120], [780, 120], [780, 150], [370, 150]],
                confidence=0.98,
            ),
            # Value left-aligned with the bilingual prefix, not the English label
            TextRegion(
                text="SHRADHANAND MEHTA",
                bbox=[[55, 160], [400, 160], [400, 195], [55, 195]],
                confidence=1.0,
            ),
        ]
        label = find_visual_field(regions, ["NAME OF FATHER", "FATHER"])
        assert label is not None
        # English label alone reports left=370; bilingual block reports 60.
        assert min(p[0] for p in label.bbox) >= 370
        assert find_label_row_left_edge(regions, label) == 60
        value = find_visual_value_near(regions, label)
        assert value is not None
        assert value.text == "SHRADHANAND MEHTA"

    def test_value_lookup_does_not_absorb_adjacent_field_value(self):
        """Multi-column biodata layouts put the value of one field on the same
        row as the label of another. Such values must NOT shift the label's
        effective left edge — only short bilingual prefixes do."""
        regions = [
            # Place-of-Issue value sitting on the same row as the next label
            TextRegion(
                text="R.S.Lakshan",
                bbox=[[80, 800], [290, 800], [290, 835], [80, 835]],
                confidence=0.93,
            ),
            # Date of issue label, in the centre column
            TextRegion(
                text="Date of issue",
                bbox=[[350, 810], [545, 810], [545, 840], [350, 840]],
                confidence=0.79,
            ),
            # The actual date value, below the date label
            TextRegion(
                text="11/10/2011",
                bbox=[[358, 845], [483, 845], [483, 875], [358, 875]],
                confidence=1.0,
            ),
            # An MRZ-shaped line at the bottom — must NOT be picked
            TextRegion(
                text="P<INDRAMADUGULA<<SITA<MAHA<LAKSHMI<<<<<<<<<<",
                bbox=[[50, 895], [720, 895], [720, 940], [50, 940]],
                confidence=0.98,
            ),
        ]
        label = find_visual_field(regions, ["DATE OF ISSUE"])
        assert label is not None
        # The neighbouring R.S.Lakshan value must NOT be absorbed into the row.
        assert find_label_row_left_edge(regions, label) >= 350
        value = find_visual_value_near(regions, label)
        assert value is not None
        assert value.text == "11/10/2011"

    def test_cross_match_dob_match(self):
        """Visual DOB matches MRZ → no DOB_MISMATCH warning."""
        mrz = _make_mrz(dob="1990-03-15")
        regions = _make_regions("DATE OF BIRTH", "1990-03-15", label_y=200, value_y=250)
        result = validate(mrz=mrz, regions=regions)
        assert "DOB_MISMATCH" not in result.warnings

    def test_cross_match_dob_mismatch(self):
        """Visual DOB differs from MRZ → DOB_MISMATCH warning."""
        mrz = _make_mrz(dob="1990-03-15")
        regions = _make_regions("DATE OF BIRTH", "1991-03-15", label_y=200, value_y=250)
        result = validate(mrz=mrz, regions=regions)
        assert "DOB_MISMATCH" in result.warnings

    def test_cross_match_dob_ignores_place_of_birth_label(self):
        """DOB matching should prefer the birth-date label over place-of-birth."""
        mrz = _make_mrz(dob="1959-09-23")
        regions = (
            _make_regions("Place of Birth", "GUNDUGOLANU", label_y=100, value_y=150)
            + _make_regions("DATE OF BIRTH", "23/09/1959", label_y=220, value_y=270)
        )
        result = validate(mrz=mrz, regions=regions)
        assert "DOB_MISMATCH" not in result.warnings

    def test_country_code_valid(self):
        """Known country code → no UNKNOWN_COUNTRY warning."""
        mrz = _make_mrz(country_code="IND")
        result = validate(mrz=mrz, regions=[])
        country_warnings = [w for w in result.warnings if "UNKNOWN_COUNTRY" in w]
        assert len(country_warnings) == 0

    def test_country_code_invalid(self):
        """Unknown country code → UNKNOWN_COUNTRY_CODE_ZZZ warning."""
        mrz = _make_mrz(country_code="ZZZ")
        result = validate(mrz=mrz, regions=[])
        assert "UNKNOWN_COUNTRY_CODE_ZZZ" in result.warnings

    def test_expiry_before_dob(self):
        """Expiry date before DOB → EXPIRY_BEFORE_DOB error."""
        mrz = _make_mrz(dob="1990-03-15", expiry="1980-01-01")
        result = validate(mrz=mrz, regions=[])
        assert "EXPIRY_BEFORE_DOB" in result.errors

    def test_confidence_weighted_average(self):
        """Explicit math check of the weighted-average formula."""
        # MRZ with all checksums valid → mrz_score = 1.0
        mrz = _make_mrz(overall_valid=True)
        # No visual labels to match → cross_score = 0.5
        # Two regions with confidence 0.80 → avg_conf = 0.80
        regions = [
            TextRegion(
                text="RANDOM TEXT",
                bbox=[[0, 0], [100, 0], [100, 30], [0, 30]],
                confidence=0.80,
            ),
            TextRegion(
                text="MORE TEXT",
                bbox=[[0, 50], [100, 50], [100, 80], [0, 80]],
                confidence=0.80,
            ),
        ]
        result = validate(mrz=mrz, regions=regions)
        # confidence = 1.0*0.4 + 0.5*0.3 + 0.8*0.3 = 0.4 + 0.15 + 0.24 = 0.79
        assert result.confidence == 0.79
