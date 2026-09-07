import pytest

from core.travel_mrz import parse_travel_mrz
from document_samples import regions, td1_lines, visa_lines


def test_us_passport_card_td1_fields_and_checks():
    result = parse_travel_mrz(regions(*td1_lines()))
    assert result.document_type == "passport_card"
    assert result.issuing_country == "US"
    assert result.fields["document_number"] == "C12345678"
    assert result.fields["given_names"] == "ANNA MARIA"
    assert result.fields["date_of_birth"] == "1990-03-15"
    assert result.fields["expiry_date"] == "2030-06-01"
    assert result.checks["mrz_checksums_valid"]
    assert result.checks["issuer_authenticated"] is False
    assert result.errors == []


@pytest.mark.parametrize("kind, expected", [("C1", "us_green_card"), ("C2", "us_green_card"), ("IA", "us_ead")])
def test_uscis_profile_keeps_a_number_separate_from_card_number(kind, expected):
    result = parse_travel_mrz(regions(*td1_lines(kind=kind, number="123456789", optional="MSC0123456789", birth_country="IND")))
    assert result.document_type == expected
    assert result.fields["uscis_number"] == "123456789"
    assert result.fields["card_number"] == "MSC0123456789"
    assert result.fields["country_of_birth"] == "IND"
    assert "document_number" not in result.fields
    assert "nationality" not in result.fields
    assert not result.errors


@pytest.mark.parametrize("width, format_name", [(44, "MRV_A"), (36, "MRV_B")])
def test_visa_formats_do_not_require_a_nonexistent_composite_check(width, format_name):
    result = parse_travel_mrz(regions(*visa_lines(width)))
    assert result.document_type == "visa"
    assert result.fields["mrz_format"] == format_name
    assert result.fields["document_number"] == "L898902C3"
    assert result.checks["mrz_checksums_valid"]
    assert "composite_checksum" not in result.checks
    assert not result.errors


def test_invalid_individual_check_is_reported():
    lines = td1_lines()
    lines[0] = lines[0][:14] + str((int(lines[0][14]) + 1) % 10) + lines[0][15:]
    result = parse_travel_mrz(regions(*lines))
    assert not result.checks["mrz_checksums_valid"]
    assert "MRZ_DOCUMENT_NUMBER_CHECKSUM_FAILED" in result.errors


def test_calendar_validity_is_independent_of_checksums():
    result = parse_travel_mrz(regions(*td1_lines(birth="900231")))
    assert result.checks["mrz_checksums_valid"]
    assert result.fields["date_of_birth"] is None
    assert "MISSING_OR_INVALID_DATE_OF_BIRTH" in result.errors


def test_multiple_documents_are_not_silently_combined():
    result = parse_travel_mrz(regions(*td1_lines(), *td1_lines(number="C87654321")))
    assert "MULTIPLE_MRZ_DOCUMENTS" in result.errors


def test_multiline_ocr_region_and_reversed_detection_order():
    assert parse_travel_mrz(regions("\n".join(td1_lines()))).fields["document_number"] == "C12345678"
    assert parse_travel_mrz(list(reversed(regions(*td1_lines())))).fields["document_number"] == "C12345678"


def test_truncated_mrz_is_not_padded_into_apparently_valid_data():
    lines = td1_lines()
    lines[1] = lines[1][:-1]
    assert parse_travel_mrz(regions(*lines)) is None


def test_german_icao_issuing_code_is_recognized():
    lines = visa_lines(36)
    lines[0] = lines[0][:2] + "D<<" + lines[0][5:]
    result = parse_travel_mrz(regions(*lines))
    assert result.issuing_country == "DE"
    assert not result.errors
