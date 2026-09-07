import pytest

from core.document_registry import list_document_profiles, normalize_country, validate_document_hint


@pytest.mark.parametrize("value, expected", [("USA", "US"), ("us", "US"), ("IND", "IN"), ("India", "IN"), ("DEU", "DE"), ("GB", "GB")])
def test_country_normalization(value, expected):
    assert normalize_country(value) == expected


@pytest.mark.parametrize("kind, country, expected", [("driving_licence", "US", "us_driver_license"), ("driver-license", None, "driving_licence"), ("W-9", "USA", "us_w9"), ("I-94", None, "us_i94"), ("ead", None, "us_ead")])
def test_explicit_country_aware_aliases(kind, country, expected):
    actual, canonical_country = validate_document_hint(kind, country)
    assert actual == expected
    assert canonical_country == ("IN" if expected == "driving_licence" else "US")


@pytest.mark.parametrize("kind, country", [("us_driver_license", "IN"), ("pan", "US"), ("fake", None), (None, "ZZZ")])
def test_invalid_hints_fail_explicitly(kind, country):
    with pytest.raises(ValueError):
        validate_document_hint(kind, country)


def test_registry_is_explicit_and_json_safe():
    profiles = {item["documentType"]: item for item in list_document_profiles()}
    assert profiles["us_driver_license"]["experimental"]
    assert profiles["passport"]["experimental"] is False
    assert profiles["us_ead"]["countries"] == ["US"]
    assert "uscisNumber" in profiles["us_ead"]["fields"]
    assert "cardNumber" in profiles["us_ead"]["fields"]
    assert set(profiles["us_w9"]["requiredFields"]) == {"name", "taxpayerId", "taxpayerIdType"}
    assert "passportNumber" in profiles["passport"]["fields"]
    assert "documentNumber" not in profiles["passport"]["fields"]
    assert profiles["pan"]["requiredFields"] == ["panNumber", "name", "dateOfBirth"]
    assert "headOfHousehold" in profiles["nrega_job_card"]["fields"]
    assert "name" not in profiles["nrega_job_card"]["fields"]
    assert profiles["aadhaar"]["requiredFieldsByVariant"]["address"] == ["aadhaarNumberOrMaskedLast4", "address", "pincode"]


@pytest.mark.parametrize("value", [123, True, [], {}])
def test_non_string_json_hints_raise_value_error(value):
    with pytest.raises(ValueError, match="INVALID_DOCUMENT_TYPE_HINT_TYPE"):
        validate_document_hint(value)
    with pytest.raises(ValueError, match="INVALID_COUNTRY_HINT_TYPE"):
        validate_document_hint(None, value)
