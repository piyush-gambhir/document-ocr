"""Tests for KYC identifier format + checksum validators (core/validators.py)."""

from core.validators import (
    extract_aadhaar_number,
    is_valid_aadhaar,
    is_valid_dl,
    is_valid_epic,
    is_valid_pan,
    normalize_dl,
    normalize_epic,
    normalize_pan,
    verhoeff_validate,
)


class TestVerhoeff:
    def test_known_valid_vector(self):
        # External truth: the Verhoeff check digit of "236" is 3 → "2363" valid.
        assert verhoeff_validate("2363") is True

    def test_known_invalid_vector(self):
        assert verhoeff_validate("2364") is False

    def test_single_digit_transposition_detected(self):
        assert verhoeff_validate("999888777669") is True
        # Transpose two adjacent digits → must fail (Verhoeff catches this).
        assert verhoeff_validate("999888777696") is False

    def test_non_digit_is_invalid(self):
        assert verhoeff_validate("12A4") is False


class TestPan:
    def test_valid_pan(self):
        assert is_valid_pan("ABCPE1234F") is True

    def test_holder_type_char_enforced(self):
        # 4th char 'D' is not a valid holder-type code.
        assert is_valid_pan("ABCDE1234Z") is False

    def test_normalize_from_noisy_text(self):
        assert normalize_pan("PAN: ABCPE1234F ") == "ABCPE1234F"

    def test_wrong_shape_rejected(self):
        assert is_valid_pan("ABC1234F") is False
        assert normalize_pan("not a pan") is None


class TestAadhaar:
    def test_grouping(self):
        assert extract_aadhaar_number("UID 9998 8877 7669 issued") == "9998 8877 7669"

    def test_valid_checksum(self):
        assert is_valid_aadhaar("9998 8877 7669") is True

    def test_invalid_checksum(self):
        assert is_valid_aadhaar("9998 8877 7660") is False

    def test_cannot_start_with_zero_or_one(self):
        assert is_valid_aadhaar("0998 8877 7669") is False


class TestEpic:
    def test_valid(self):
        assert is_valid_epic("ABC1234567") is True
        assert normalize_epic("EPIC No. ABC1234567") == "ABC1234567"

    def test_invalid(self):
        assert is_valid_epic("AB1234567") is False


class TestDl:
    def test_valid_with_spaces(self):
        assert normalize_dl("MH12 2011 0012345") == "MH1220110012345"
        assert is_valid_dl("MH1220110012345") is True

    def test_invalid(self):
        assert is_valid_dl("MH-12-XYZ") is False
