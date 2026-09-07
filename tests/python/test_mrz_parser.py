"""TD3 field extraction, calendar handling, OCR repair, and checksum regressions."""

from datetime import date

import pytest

from core.mrz_parser import _parse_mrz_date, icao_check_digit, parse_mrz, verify_check_digit
from core.ocr_engine import TextRegion


# ICAO Doc 9303-4 specimen. Keep all 44 positions explicit: padding or slicing
# a malformed fixture could hide a parser offset or checksum regression.
LINE1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def _region(text: str, y: int) -> TextRegion:
    return TextRegion(text=text, bbox=[[0, y], [800, y], [800, y + 30], [0, y + 30]], confidence=0.99)


def _parse(line2: str = LINE2, line1: str = LINE1):
    return parse_mrz([_region(line1, 400), _region(line2, 440)])


def _with_composite(line2: str) -> str:
    composite = line2[:10] + line2[13:20] + line2[21:43]
    return line2[:43] + str(icao_check_digit(composite))


class TestICAOCheckDigit:
    @pytest.mark.parametrize("data, digit", [("L898902C3", 6), ("740812", 2), ("120415", 9), ("<<<", 0)])
    def test_known_check_digits(self, data, digit):
        assert icao_check_digit(data) == digit
        assert verify_check_digit(data, str(digit))

    @pytest.mark.parametrize("expected", ["5", "X", "", "06", " 6", "٦"])
    def test_requires_one_matching_ascii_digit(self, expected):
        assert not verify_check_digit("L898902C3", expected)

    def test_invalid_characters_are_not_treated_as_fillers(self):
        with pytest.raises(ValueError, match="Invalid MRZ character"):
            icao_check_digit("?")
        assert not verify_check_digit("?", "0")


class TestDateParsing:
    REFERENCE_DATE = date(2026, 9, 7)

    @pytest.mark.parametrize(
        "raw, is_expiry, expected",
        [
            ("900315", False, "1990-03-15"),
            ("260101", False, "2026-01-01"),
            ("261001", False, "1926-10-01"),
            ("290601", False, "1929-06-01"),
            ("300601", False, "1930-06-01"),
            ("300601", True, "2030-06-01"),
            ("350601", True, "2035-06-01"),
            ("120415", True, "2012-04-15"),
            ("240229", False, "2024-02-29"),
        ],
    )
    def test_resolves_century_by_field(self, raw, is_expiry, expected):
        assert _parse_mrz_date(raw, is_expiry=is_expiry, reference_date=self.REFERENCE_DATE) == expected

    @pytest.mark.parametrize("raw", ["901301", "900132", "900231", "230229", "900431", "ABCDEF", "<<<<<<", "９００３１５"])
    def test_rejects_invalid_calendar_dates(self, raw):
        assert _parse_mrz_date(raw, reference_date=self.REFERENCE_DATE) is None

    def test_expiry_crosses_a_century(self):
        assert _parse_mrz_date("010101", is_expiry=True, reference_date=date(2098, 1, 1)) == "2101-01-01"


class TestParseMRZ:
    def test_icao_specimen_fields_and_all_checksums(self):
        assert len(LINE1) == len(LINE2) == 44
        result = _parse()
        assert result is not None
        assert result.document_type.value == "P"
        assert result.surname.value == "ERIKSSON"
        assert result.given_names.value == "ANNA MARIA"
        assert result.country_code.value == result.nationality.value == "UTO"
        assert result.passport_number.value == "L898902C3"
        assert result.date_of_birth.value == "1974-08-12"
        assert result.expiry_date.value == "2012-04-15"
        assert result.sex.value == "F"
        assert result.personal_number.value == "ZE184226B"
        assert all(field.checksum_valid for field in (
            result.passport_number, result.date_of_birth, result.expiry_date, result.personal_number
        ))
        assert result.overall_checksum_valid
        assert result.errors == []

    @pytest.mark.parametrize("regions", [[], [_region("PASSPORT", 0)], [_region("A" * 44, 400), _region("B" * 44, 440)]])
    def test_rejects_non_mrz_regions(self, regions):
        assert parse_mrz(regions) is None

    def test_2030_expiry_is_not_1930(self):
        expiry = "300601"
        line2 = _with_composite(LINE2[:21] + expiry + str(icao_check_digit(expiry)) + LINE2[28:])
        result = _parse(line2)
        assert result.expiry_date.value == "2030-06-01"
        assert result.overall_checksum_valid

    def test_footer_does_not_displace_mrz(self):
        regions = [_region(LINE1, 400), _region(LINE2, 440), _region("A" * 44, 480)]
        result = parse_mrz(list(reversed(regions)))
        assert result is not None
        assert result.raw_lines == (LINE1, LINE2)
        assert result.overall_checksum_valid

    def test_letter_prefixed_passport_number_is_not_a_second_header(self):
        passport_number = "PALAB1234"
        line2 = _with_composite(passport_number + str(icao_check_digit(passport_number)) + LINE2[10:])
        result = _parse(line2)
        assert result is not None
        assert result.passport_number.value == passport_number
        assert result.overall_checksum_valid

    def test_digit_correction_recovers_dates_without_changing_alphanumeric_fields(self):
        line2 = list(LINE2)
        line2[15] = "O"  # 0 in 740812
        line2[17] = "I"  # 1 in 740812
        result = _parse("".join(line2))
        assert result.date_of_birth.value == "1974-08-12"
        assert result.date_of_birth.checksum_valid
        assert result.passport_number.value == "L898902C3"
        assert result.personal_number.value == "ZE184226B"
        assert result.surname.value == "ERIKSSON"
        assert result.overall_checksum_valid

    @pytest.mark.parametrize(
        "position, replacement, field, error",
        [(9, "5", "passport_number", "PASSPORT_NUMBER_CHECKSUM_FAILED"),
         (19, "9", "date_of_birth", "DOB_CHECKSUM_FAILED"),
         (27, "0", "expiry_date", "EXPIRY_CHECKSUM_FAILED"),
         (42, "0", "personal_number", "PERSONAL_NUMBER_CHECKSUM_FAILED")],
    )
    def test_bad_field_check_cannot_be_hidden_by_valid_composite(self, position, replacement, field, error):
        line2 = _with_composite(LINE2[:position] + replacement + LINE2[position + 1:])
        result = _parse(line2)
        assert not getattr(result, field).checksum_valid
        assert not result.overall_checksum_valid
        assert error in result.errors
        assert "OVERALL_CHECKSUM_FAILED" not in result.errors

    def test_bad_composite_with_valid_individual_checks(self):
        result = _parse(LINE2[:43] + "9")
        assert result.passport_number.checksum_valid
        assert not result.overall_checksum_valid
        assert result.errors == ["OVERALL_CHECKSUM_FAILED"]

    @pytest.mark.parametrize("check", ["0", "<"])
    def test_unused_optional_data_accepts_zero_or_filler(self, check):
        result = _parse(_with_composite(LINE2[:28] + "<" * 14 + check + "0"))
        assert result.personal_number.value is None
        assert result.personal_number.checksum_valid
        assert result.overall_checksum_valid

    def test_used_optional_data_requires_numeric_check(self):
        result = _parse(_with_composite(LINE2[:42] + "<0"))
        assert not result.personal_number.checksum_valid
        assert not result.overall_checksum_valid

    def test_ocr_filler_substitutions_and_whitespace(self):
        result = _parse(LINE2.replace("<", ">"), LINE1.replace("<", "‹") + "\t\n")
        assert result.given_names.value == "ANNA MARIA"
        assert result.overall_checksum_valid


def test_padding_noise_is_not_an_extra_given_name_and_raw_is_preserved():
    noisy = LINE1[:35] + 'ZZ' + LINE1[37:]
    result = _parse(line1=noisy)
    assert result.given_names.value == 'ANNA MARIA'
    assert result.raw_lines[0] == noisy
    assert 'MRZ_NAME_PADDING_NOISE' in result.errors
    assert result.overall_checksum_valid  # Line-one names have no check digit.


def test_single_fillers_preserve_all_given_name_components():
    line = 'P<UTOERIKSSON<<ANNA<MARIA<ROSE'.ljust(44, '<')
    result = _parse(line1=line)
    assert result.given_names.value == 'ANNA MARIA ROSE'
    assert 'MRZ_NAME_PADDING_NOISE' not in result.errors
