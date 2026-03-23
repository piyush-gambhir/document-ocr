"""Tests for cross-validation and confidence scoring (core/validator.py)."""

import pytest

from core.validator import validate, ValidationResult
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
