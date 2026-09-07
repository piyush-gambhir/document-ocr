"""Explicit document capabilities and normalized country/type hints."""

from __future__ import annotations

from dataclasses import dataclass

import pycountry


@dataclass(frozen=True)
class DocumentProfile:
    document_type: str
    name: str
    countries: tuple[str, ...]
    fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    extraction_methods: tuple[str, ...]
    experimental: bool = True
    legacy: bool = False


_IDENTITY = ("surname", "given_names", "date_of_birth", "document_number", "expiry_date")
_ADDRESS = ("address", "city", "state", "postal_code")
_MRZ = ("country_code", "mrz_raw")
_PROFILES = (
    DocumentProfile("passport", "Passport book", ("*",), ("surname", "given_names", "full_name", "passport_number", "nationality", "date_of_birth", "sex", "expiry_date", "issue_date", "place_of_birth", "country_code"), ("surname", "passport_number"), ("mrz", "ocr"), False, True),
    DocumentProfile("pan", "Indian PAN card", ("IN",), ("pan_number", "name", "father_name", "date_of_birth"), ("pan_number", "name", "date_of_birth"), ("ocr",), False, True),
    DocumentProfile("aadhaar", "Indian Aadhaar card", ("IN",), ("aadhaar_number", "name", "date_of_birth", "year_of_birth", "gender", "address", "pincode", "checksum_valid", "aadhaar_masked", "aadhaar_last4", "vid"), ("aadhaar_number_or_masked_last4", "name", "date_or_year_of_birth", "gender"), ("ocr",), False, True),
    DocumentProfile("driving_licence", "Indian driving licence", ("IN",), ("dl_number", "name", "date_of_birth", "issue_date", "validity_date", "address", "relation_name", "blood_group", "class_of_vehicle", "validity_date_transport"), ("dl_number", "name", "date_of_birth", "issue_date", "validity_date"), ("ocr",), False, True),
    DocumentProfile("voter_id", "Indian voter ID", ("IN",), ("epic_number", "name", "relation_name", "relation_type", "gender", "date_of_birth", "age"), ("epic_number", "name", "date_of_birth_or_age"), ("ocr",), False, True),
    DocumentProfile("nrega_job_card", "Indian NREGA job card", ("IN",), ("job_card_number", "head_of_household", "category", "registration_date", "validity_from", "validity_to", "address", "village", "gram_panchayat", "block", "district", "state", "bpl_status", "family_id", "members"), ("job_card_number", "household_or_member_name", "location"), ("ocr",), True, True),
    DocumentProfile("npr_letter", "Indian NPR letter", ("IN",), ("reference_number", "name", "address", "pincode", "issue_date"), ("name", "address"), ("ocr",), True, True),
    DocumentProfile("us_driver_license", "US driver license", ("US",), _IDENTITY + _ADDRESS + ("first_name", "middle_names", "issue_date", "sex", "license_class", "restrictions", "endorsements"), ("surname", "document_number", "date_of_birth", "expiry_date"), ("pdf417", "ocr")),
    DocumentProfile("us_state_id", "US state identification card", ("US",), _IDENTITY + _ADDRESS + ("first_name", "middle_names", "issue_date", "sex"), ("surname", "document_number", "date_of_birth", "expiry_date"), ("pdf417", "ocr")),
    DocumentProfile("passport_card", "Passport card", ("*",), _IDENTITY + ("nationality", "sex", "issue_date", "address") + _MRZ, ("surname", "document_number", "date_of_birth", "expiry_date"), ("mrz", "ocr")),
    DocumentProfile("us_green_card", "US Permanent Resident Card (I-551)", ("US",), ("surname", "given_names", "uscis_number", "card_number", "date_of_birth", "expiry_date", "category", "resident_since", "country_of_birth", "sex") + _MRZ, ("surname", "uscis_number", "card_number", "date_of_birth"), ("mrz", "ocr")),
    DocumentProfile("us_ead", "US Employment Authorization Document (I-766)", ("US",), ("surname", "given_names", "uscis_number", "card_number", "date_of_birth", "expiry_date", "category", "valid_from", "country_of_birth", "sex") + _MRZ, ("surname", "uscis_number", "card_number", "date_of_birth", "expiry_date"), ("mrz", "ocr")),
    DocumentProfile("visa", "Machine-readable visa (MRV-A / MRV-B)", ("*",), _IDENTITY + ("nationality", "sex", "mrz_format") + _MRZ, ("surname", "document_number", "date_of_birth", "expiry_date"), ("mrz", "ocr")),
    DocumentProfile("us_i94", "US I-94 arrival/departure record", ("US",), ("i94_number", "surname", "given_names", "date_of_birth", "admission_date", "admit_until", "class_of_admission", "passport_number", "country_of_citizenship"), ("i94_number", "surname", "class_of_admission", "admit_until"), ("ocr",)),
    DocumentProfile("us_w9", "US Form W-9", ("US",), ("name", "business_name", "taxpayer_id", "taxpayer_id_type", "address", "city_state_postal_code"), ("name", "taxpayer_id", "taxpayer_id_type"), ("ocr",)),
)
DOCUMENT_PROFILES = {profile.document_type: profile for profile in _PROFILES}


def normalize_country(country: str | None) -> str | None:
    if country is None:
        return None
    if not isinstance(country, str):
        raise ValueError("INVALID_COUNTRY_HINT_TYPE")
    value = country.strip().upper()
    aliases = {"USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "IND": "IN", "INDIA": "IN", "UK": "GB"}
    value = aliases.get(value, value)
    result = pycountry.countries.get(alpha_2=value) if len(value) == 2 else pycountry.countries.get(alpha_3=value)
    if result is None:
        raise ValueError(f"UNSUPPORTED_COUNTRY: {country}")
    return result.alpha_2


def validate_document_hint(document_type: str | None, country: str | None = None) -> tuple[str | None, str | None]:
    """Return canonical hints or fail explicitly instead of ignoring a conflict."""
    country = normalize_country(country)
    if document_type is None:
        return None, country
    if not isinstance(document_type, str):
        raise ValueError("INVALID_DOCUMENT_TYPE_HINT_TYPE")
    value = document_type.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "driver_license": "driving_licence", "driving_license": "driving_licence",
        "drivers_license": "driving_licence", "state_id": "us_state_id",
        "green_card": "us_green_card", "i551": "us_green_card", "i_551": "us_green_card",
        "ead": "us_ead", "i766": "us_ead", "i_766": "us_ead",
        "i94": "us_i94", "i_94": "us_i94", "w9": "us_w9", "w_9": "us_w9",
        "us_passport": "passport", "passport_book": "passport",
    }
    value = aliases.get(value, value)
    if value == "driving_licence" and country == "US":
        value = "us_driver_license"
    profile = DOCUMENT_PROFILES.get(value)
    if profile is None:
        raise ValueError(f"UNSUPPORTED_DOCUMENT_TYPE: {document_type}")
    if country is not None and "*" not in profile.countries and country not in profile.countries:
        raise ValueError(f"DOCUMENT_COUNTRY_MISMATCH: {value}/{country}")
    if country is None and len(profile.countries) == 1 and profile.countries[0] != "*":
        country = profile.countries[0]
    return value, country


def list_document_profiles() -> list[dict]:
    """Return JSON-safe metadata, including experimental support boundaries."""
    def camel(value: str) -> str:
        head, *tail = value.split("_")
        return head + "".join(part.title() for part in tail)

    profiles = [
        {
            "documentType": profile.document_type,
            "label": profile.name,
            "countries": list(profile.countries),
            "fields": [camel(name) for name in profile.fields],
            "requiredFields": [camel(name) for name in profile.required_fields],
            "sources": list(profile.extraction_methods),
            "experimental": profile.experimental,
        }
        for profile in _PROFILES
    ]
    # The legacy completion rules contain alternatives and, for Aadhaar,
    # different front/address-side requirements. Expose those explicitly rather
    # than pretending every logical requirement is one physical output field.
    for profile in profiles:
        if profile["documentType"] == "aadhaar":
            profile["requiredFieldsByVariant"] = {
                "front": profile["requiredFields"].copy(),
                "address": ["aadhaarNumberOrMaskedLast4", "address", "pincode"],
            }
            profile["requirementAlternatives"] = {
                "aadhaarNumberOrMaskedLast4": [["aadhaarNumber"], ["aadhaarMasked", "aadhaarLast4"]],
                "dateOrYearOfBirth": [["dateOfBirth"], ["yearOfBirth"]],
            }
        elif profile["documentType"] == "voter_id":
            profile["requirementAlternatives"] = {"dateOfBirthOrAge": [["dateOfBirth"], ["age"]]}
        elif profile["documentType"] == "nrega_job_card":
            profile["requirementAlternatives"] = {
                "householdOrMemberName": [["headOfHousehold"], ["members[].name"]],
                "location": [["village"], ["gramPanchayat"], ["district"], ["address"]],
            }
    return profiles
