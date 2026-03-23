"""Tests for MRZ parsing and ICAO check digit validation."""

import pytest

from core.mrz_parser import icao_check_digit, verify_check_digit, parse_mrz, _parse_mrz_date
from core.ocr_engine import TextRegion


class TestICAOCheckDigit:
    def test_numeric_string(self):
        # Example: passport number "L898902C3" check digit = 6
        assert icao_check_digit("L898902C3") == 6

    def test_all_fillers(self):
        assert icao_check_digit("<<<") == 0

    def test_verify_valid(self):
        assert verify_check_digit("L898902C3", "6") is True

    def test_verify_invalid(self):
        assert verify_check_digit("L898902C3", "5") is False

    def test_verify_non_digit(self):
        assert verify_check_digit("L898902C3", "X") is False


class TestDateParsing:
    def test_recent_year(self):
        assert _parse_mrz_date("900315") == "1990-03-15"

    def test_future_year(self):
        assert _parse_mrz_date("260101") == "2026-01-01"

    def test_boundary_29(self):
        assert _parse_mrz_date("290601") == "2029-06-01"

    def test_boundary_30(self):
        assert _parse_mrz_date("300601") == "1930-06-01"

    def test_invalid_month(self):
        assert _parse_mrz_date("901301") is None

    def test_invalid_day(self):
        assert _parse_mrz_date("900132") is None

    def test_non_numeric(self):
        assert _parse_mrz_date("ABCDEF") is None


class TestParseMRZ:
    def _make_regions(self, line1: str, line2: str) -> list[TextRegion]:
        """Create fake OCR regions from two MRZ lines."""
        return [
            TextRegion(text=line1, bbox=[[0, 400], [800, 400], [800, 430], [0, 430]], confidence=0.99),
            TextRegion(text=line2, bbox=[[0, 440], [800, 440], [800, 470], [0, 470]], confidence=0.99),
        ]

    def test_valid_passport(self):
        # Sample TD3 passport MRZ (ICAO example)
        line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<<<"
        line2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"

        # Pad to 44
        line1 = line1.ljust(44, "<")[:44]
        line2 = line2.ljust(44, "<")[:44]

        regions = self._make_regions(line1, line2)
        result = parse_mrz(regions)

        assert result is not None
        assert result.surname.value == "ERIKSSON"
        assert result.given_names.value == "ANNA MARIA"
        assert result.country_code.value == "UTO"
        assert result.passport_number.value == "L898902C3"
        assert result.nationality.value == "UTO"
        assert result.sex.value == "F"

    def test_no_mrz_lines(self):
        regions = [
            TextRegion(text="Republic of India", bbox=[[0, 0], [200, 0], [200, 30], [0, 30]], confidence=0.95),
            TextRegion(text="PASSPORT", bbox=[[0, 40], [200, 40], [200, 70], [0, 70]], confidence=0.98),
        ]
        result = parse_mrz(regions)
        assert result is None

    def test_empty_regions(self):
        result = parse_mrz([])
        assert result is None


class TestMRZEdgeCases:
    """Edge-case tests for MRZ parsing: OCR error correction, checksum
    corruption, and symbol substitution."""

    # ICAO example passport
    LINE1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<".ljust(44, "<")[:44]
    LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10".ljust(44, "<")[:44]

    def _make_regions(self, line1: str, line2: str) -> list[TextRegion]:
        """Create fake OCR regions from two MRZ lines."""
        return [
            TextRegion(text=line1, bbox=[[0, 400], [800, 400], [800, 430], [0, 430]], confidence=0.99),
            TextRegion(text=line2, bbox=[[0, 440], [800, 440], [800, 470], [0, 470]], confidence=0.99),
        ]

    def test_digit_correction_in_date_fields(self):
        """OCR-confused letters in date positions should be auto-corrected.

        DOB is at positions 13-18 of line 2.  Original: '740812'.
        Replace '0' with 'O' (pos 14) and '1' with 'I' (pos 17) →
        '74O8I2'.  Digit correction should fix O→0 and I→1.
        """
        line2 = list(self.LINE2)
        # Position 14 is '4' in '740812' — pick position 13 which is '7'
        # Actually positions 13-18 are '740812'. Corrupt pos 14 ('4'→'A' maps to '4')
        # and pos 17 ('1'→'I' maps to '1').
        line2[14] = "O"  # pos 14 was '4', O → 0 via digit correction → DOB becomes '700812'
        line2[17] = "I"  # pos 17 was '1', I → 1 via digit correction → stays '1'
        line2_str = "".join(line2)

        regions = self._make_regions(self.LINE1, line2_str)
        result = parse_mrz(regions)

        assert result is not None
        assert result.date_of_birth.value is not None
        # DOB raw becomes '700812' (O→0 at pos 14) → 1970-08-12
        assert result.date_of_birth.value == "1970-08-12"

    def test_digit_correction_preserves_names(self):
        """Digit correction must NOT corrupt alphabetic fields in line 1."""
        # Use the exact ICAO lines — names should parse cleanly
        regions = self._make_regions(self.LINE1, self.LINE2)
        result = parse_mrz(regions)

        assert result is not None
        assert result.surname.value == "ERIKSSON"
        assert result.given_names.value == "ANNA MARIA"

    def test_checksum_failure_passport_number(self):
        """Corrupt the passport number check digit (pos 9) → checksum_valid=False."""
        line2 = list(self.LINE2)
        # Original check digit at pos 9 is '6'. Change to '5'.
        line2[9] = "5"
        line2_str = "".join(line2)

        regions = self._make_regions(self.LINE1, line2_str)
        result = parse_mrz(regions)

        assert result is not None
        assert result.passport_number.checksum_valid is False

    def test_checksum_failure_dob(self):
        """Corrupt the DOB check digit (pos 19) → date_of_birth.checksum_valid=False."""
        line2 = list(self.LINE2)
        # Original check digit at pos 19 is '2'. Change to '9'.
        line2[19] = "9"
        line2_str = "".join(line2)

        regions = self._make_regions(self.LINE1, line2_str)
        result = parse_mrz(regions)

        assert result is not None
        assert result.date_of_birth.checksum_valid is False

    def test_overall_checksum_failure(self):
        """Corrupt the overall check digit (pos 43) → overall_checksum_valid=False."""
        line2 = list(self.LINE2)
        # Original overall check digit at pos 43 is '0'. Change to '9'.
        line2[43] = "9"
        line2_str = "".join(line2)

        regions = self._make_regions(self.LINE1, line2_str)
        result = parse_mrz(regions)

        assert result is not None
        assert result.overall_checksum_valid is False

    def test_mrz_with_greater_than_signs(self):
        """'>' substituted for '<' (common OCR error) should still parse."""
        line1 = self.LINE1.replace("<", ">")
        line2 = self.LINE2.replace("<", ">")

        regions = self._make_regions(line1, line2)
        result = parse_mrz(regions)

        assert result is not None
        assert result.surname.value == "ERIKSSON"
        assert result.given_names.value == "ANNA MARIA"
        assert result.passport_number.value == "L898902C3"
