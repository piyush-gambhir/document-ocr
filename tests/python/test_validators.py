"""Tests for KYC identifier format + checksum validators (core/validators.py)."""

import pytest

from core.validators import (
    extract_aadhaar_number,
    is_valid_aadhaar,
    is_valid_dl,
    is_valid_epic,
    is_valid_nrega_job_card,
    is_valid_pan,
    normalize_dl,
    normalize_epic,
    normalize_nrega_job_card,
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

    @pytest.mark.parametrize("value", ["", "²363", "２３６３", "٢٣٦٣"])
    def test_rejects_non_ascii_digits_without_crashing(self, value):
        assert verhoeff_validate(value) is False


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

    def test_repeated_spacing_is_accepted(self):
        assert extract_aadhaar_number("9998  8877\t\t7669") == "9998 8877 7669"
        assert is_valid_aadhaar("9998  8877\t\t7669")

    def test_unrelated_lines_are_not_joined_into_an_identifier(self):
        assert extract_aadhaar_number("9998\n8877\n7669") is None

    def test_non_ascii_digits_are_not_aadhaar_identifiers(self):
        assert extract_aadhaar_number("９９９８ ８８７７ ７６６９") is None


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


class TestNregaJobCard:
    def test_valid_hierarchical_number(self):
        assert (
            normalize_nrega_job_card("RJ-27-001-002-0008147/00")
            == "RJ-27-001-002-0008147/00"
        )
        assert is_valid_nrega_job_card("UP-65-001-003-00876700/342") is True

    def test_requires_state_and_multiple_numeric_components(self):
        assert is_valid_nrega_job_card("JOB-CARD-123") is False
        assert is_valid_nrega_job_card("RJ-27-123") is False
        assert is_valid_nrega_job_card("ABCDE1234F") is False


@pytest.mark.parametrize(
    "normalize, validate, identifier",
    [(normalize_pan, is_valid_pan, "ABCPE1234F"),
     (normalize_epic, is_valid_epic, "ABC1234567"),
     (normalize_dl, is_valid_dl, "MH1220110012345")],
)
class TestIdentifierBoundaries:
    @pytest.mark.parametrize("prefix, suffix", [("X", ""), ("", "1"), ("1", ""), ("", "X")])
    def test_does_not_slice_a_larger_token(self, normalize, validate, identifier, prefix, suffix):
        text = prefix + identifier + suffix
        assert normalize(text) is None
        assert not validate(text)

    def test_keeps_labels_and_ocr_grouping(self, normalize, validate, identifier):
        text = "Number: " + " ".join(identifier) + " issued"
        assert normalize(text) == identifier
        assert validate(text)

    def test_does_not_remove_arbitrary_corrupt_characters(self, normalize, validate, identifier):
        text = identifier[:6] + "?" + identifier[6:]
        assert normalize(text) is None
        assert not validate(text)
