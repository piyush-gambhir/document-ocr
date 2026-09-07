import pytest

from core.barcodes import BarcodeResult
from core.structured_documents import extract_structured_document
from document_samples import aamva_payload, regions, td1_lines, visa_lines


def test_pdf417_only_us_driver_license_has_evidence_and_no_authenticity_claim():
    barcode = BarcodeResult("PDF417", aamva_payload(), [[1, 2], [3, 2], [3, 4], [1, 4]])
    result = extract_structured_document([], barcodes=[barcode])
    assert result.document_type == "us_driver_license"
    assert result.issuing_country == "US"
    assert result.issuing_region == "VA"
    assert result.fields["postal_code"] == "023269000"
    assert result.fields["date_of_birth"] == "2006-06-06"
    assert result.complete
    assert result.checks["signature_verified"] is False
    assert result.field_evidence["document_number"][0]["source"] == "pdf417"


def test_state_id_subfile_is_a_separate_type():
    result = extract_structured_document([], barcodes=[BarcodeResult("PDF417", aamva_payload(kind="ID"), [])])
    assert result.document_type == "us_state_id"
    assert result.complete


def test_first_and_middle_names_are_not_incorrectly_reported_as_a_conflict():
    result = extract_structured_document(regions("First Name: MICHAEL", "FN: MICHAEL JOHN"), barcodes=[BarcodeResult("PDF417", aamva_payload(), [])])
    assert result.fields["given_names"] == "MICHAEL JOHN"
    assert result.fields["first_name"] == "MICHAEL"
    assert result.complete


def test_front_only_driver_license_is_explicitly_lower_evidence():
    result = extract_structured_document(regions("CALIFORNIA DRIVER LICENSE", "LN: SAMPLE", "FN: ANNA", "DL: A1234567", "DOB: 03/15/1990", "EXP: 06/01/2030"))
    assert result.document_type == "us_driver_license"
    assert result.issuing_region == "CA"
    assert result.complete
    assert "PDF417_NOT_DECODED" in result.warnings


def test_id_card_title_is_not_used_as_the_card_number():
    result = extract_structured_document(regions("VIRGINIA IDENTIFICATION CARD", "ID CARD", "LN: SAMPLE", "DOB: 03/15/1990", "EXP: 06/01/2030"))
    assert "document_number" not in result.fields
    assert not result.complete


def test_barcode_visual_disagreement_preserves_both_sources_and_fails_complete():
    result = extract_structured_document(regions("Surname: DIFFERENT"), barcodes=[BarcodeResult("PDF417", aamva_payload(), [])])
    assert result.fields["surname"] == "SAMPLE"
    assert "FIELD_MISMATCH_SURNAME" in result.errors
    assert not result.complete
    assert {item["source"] for item in result.field_evidence["surname"]} == {"pdf417", "ocr"}


def test_canadian_aamva_is_not_mislabeled_as_us():
    result = extract_structured_document([], barcodes=[BarcodeResult("PDF417", aamva_payload(overrides={"DCG": "CAN", "DAJ": "ON"}), [])])
    assert result is None


def test_unknown_explicit_aamva_country_is_not_inferred_from_state():
    result = extract_structured_document([], barcodes=[BarcodeResult("PDF417", aamva_payload(overrides={"DCG": "XYZ", "DAJ": "VA"}), [])])
    assert result is None


def test_mixed_machine_readable_documents_are_not_silently_collapsed():
    result = extract_structured_document(regions(*td1_lines()), barcodes=[BarcodeResult("PDF417", aamva_payload(), [])])
    assert "MULTIPLE_MACHINE_READABLE_DOCUMENTS" in result.errors
    assert not result.complete


@pytest.mark.parametrize("field, value", [("DBB", "02312000"), ("DBA", "13312030")])
def test_invalid_aamva_dates_are_reported(field, value):
    result = extract_structured_document([], barcodes=[BarcodeResult("PDF417", aamva_payload(overrides={field: value}), [])])
    assert not result.complete
    assert any(error.startswith("INVALID_") for error in result.errors)


def test_country_hint_is_checked_against_actual_document():
    result = extract_structured_document(regions(*td1_lines(issuer="IRL")), country="US")
    assert result.issuing_country == "IE"
    assert "DOCUMENT_COUNTRY_MISMATCH" in result.errors


def test_document_type_hint_is_checked_against_actual_document():
    result = extract_structured_document(regions(*td1_lines()), document_type="us_ead")
    assert result.document_type == "passport_card"
    assert "DOCUMENT_TYPE_MISMATCH" in result.errors


@pytest.mark.parametrize("lines", [("DRIVER LICENSE", "Name: Someone", "DOB: 01/01/1990"), ("W-9 information", "SSN: 123-45-6789"), ("I-94", "Family Name: SOMEONE")])
def test_generic_mentions_do_not_trigger_sensitive_field_extraction(lines):
    assert extract_structured_document(regions(*lines)) is None


def test_hint_alone_is_not_document_evidence():
    result = extract_structured_document(regions("Name: Someone", "SSN: 123-45-6789"), document_type="us_w9")
    assert result.fields == {}
    assert "DOCUMENT_TYPE_NOT_CONFIRMED" in result.errors
    assert not result.complete


def test_i94_alphanumeric_number_and_duration_of_status():
    result = extract_structured_document(regions(
        "I-94 Arrival/Departure Record", "Admission (I-94) Record Number: 123456789A1",
        "Family Name: SAMPLE", "First (Given) Name: ANNA", "Birth Date: 03/15/1990",
        "Class of Admission: F1", "Admit Until Date: D/S", "Most Recent Date of Entry: 08/01/2026",
    ))
    assert result.document_type == "us_i94"
    assert result.fields["i94_number"] == "123456789A1"
    assert result.fields["admit_until"] == "D/S"
    assert result.fields["date_of_birth"] == "1990-03-15"
    assert result.complete


def test_w9_ssn_and_name_are_explicitly_labeled():
    result = extract_structured_document(regions(
        "Form W-9", "Request for Taxpayer Identification Number and Certification",
        "1 Name: SAMPLE PERSON", "Social security number: 123-45-6789",
        "5 Address: 123 MAIN STREET", "6 City, state, and ZIP code: BOSTON MA 02108",
    ))
    assert result.document_type == "us_w9"
    assert result.fields["taxpayer_id"] == "123456789"
    assert result.fields["taxpayer_id_type"] == "ssn"
    assert result.fields["name"] == "SAMPLE PERSON"
    assert result.complete


def test_w9_with_both_tin_types_is_ambiguous():
    result = extract_structured_document(regions(
        "Form W-9", "Request for Taxpayer Identification Number and Certification",
        "1 Name: EXAMPLE COMPANY", "Social security number: 123-45-6789",
        "Employer identification number: 12-3456789",
    ))
    assert "FIELD_MISMATCH_TAXPAYER_ID_TYPE" in result.errors
    assert not result.complete


def test_blank_w9_name_does_not_borrow_next_business_name_value():
    result = extract_structured_document(regions(
        "Form W-9", "Request for Taxpayer Identification Number and Certification",
        "1 Name", "2 Business name", "EXAMPLE BUSINESS",
        "Social security number: 123-45-6789",
    ))
    assert "name" not in result.fields
    assert result.fields["business_name"] == "EXAMPLE BUSINESS"
    assert not result.complete


def test_legacy_passports_still_return_to_existing_pipeline():
    assert extract_structured_document(regions("PASSPORT"), document_type="passport", country="US") is None


@pytest.mark.parametrize("lines, kind", [(td1_lines(), "passport_card"), (visa_lines(36), "visa"), (td1_lines(kind="IA", number="123456789", optional="MSC0123456789"), "us_ead")])
def test_travel_profiles_finish_with_required_fields(lines, kind):
    result = extract_structured_document(regions(*lines))
    assert result.document_type == kind
    assert result.complete


def test_uscis_country_name_agrees_with_mrz_country_code():
    result = extract_structured_document(regions(*td1_lines(kind="IA", number="123456789", optional="MSC0123456789", birth_country="IND"), "Country of Birth: India"))
    assert result.fields["country_of_birth"] == "IND"
    assert result.complete
