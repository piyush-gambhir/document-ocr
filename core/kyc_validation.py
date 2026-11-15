"""Validation and confidence assessment for non-passport document extraction.

This module deliberately separates three different questions:

* did OCR classify the document family?
* did the extractor return the minimum fields needed for that family?
* does the printed identifier pass the validation that is possible offline?

It does not establish document authenticity. Format checks and Aadhaar's
Verhoeff checksum can reject obvious OCR errors, but issuer verification
requires the appropriate signed QR, digital signature, or issuer service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import fmean
from typing import Any, Optional

from .ocr_engine import TextRegion
from .validators import (
    is_valid_aadhaar,
    is_valid_dl,
    is_valid_epic,
    is_valid_nrega_job_card,
    is_valid_pan,
)

MIN_OCR_GEOMETRY_CONFIDENCE_FOR_SUCCESS = 0.5


@dataclass
class KycExtractionAssessment:
    """Outcome of document-specific extraction validation."""

    complete: bool
    confidence: float
    identifier_valid: Optional[bool]
    missing_required_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def assess_kyc_extraction(
    document_type: str,
    extracted: Any,
    regions: list[TextRegion],
) -> KycExtractionAssessment:
    """Validate one non-passport extraction and estimate extraction confidence.

    Confidence is an explicit heuristic built from required-field completeness,
    identifier validation, and OCR-region confidence. It is intentionally
    capped for partial or invalid records and must not be interpreted as a
    calibrated probability until measured against a private evaluation set.
    """

    if document_type == "pan":
        required = {
            "panNumber": _value(extracted, "pan_number"),
            "name": _value(extracted, "name"),
            "dateOfBirth": _value(extracted, "date_of_birth"),
        }
        identifier = _value(extracted, "pan_number")
        identifier_valid: Optional[bool] = bool(
            identifier and is_valid_pan(identifier)
        )
        warnings: list[str] = []
    elif document_type == "aadhaar":
        return _assess_aadhaar(extracted, regions)
    elif document_type == "driving_licence":
        required = {
            "dlNumber": _value(extracted, "dl_number"),
            "name": _value(extracted, "name"),
            "dateOfBirth": _value(extracted, "date_of_birth"),
            "issueDate": _value(extracted, "issue_date"),
            "validityDate": _value(extracted, "validity_date"),
        }
        identifier = _value(extracted, "dl_number")
        identifier_valid = bool(identifier and is_valid_dl(identifier))
        warnings = []
    elif document_type == "voter_id":
        required = {
            "epicNumber": _value(extracted, "epic_number"),
            "name": _value(extracted, "name"),
            "dateOfBirthOrAge": (
                _value(extracted, "date_of_birth") or _value(extracted, "age")
            ),
        }
        identifier = _value(extracted, "epic_number")
        identifier_valid = bool(identifier and is_valid_epic(identifier))
        warnings = []
    elif document_type == "nrega_job_card":
        members = _value(extracted, "members") or []
        member_names = [
            _value(member, "name")
            for member in members
            if _value(member, "name")
        ]
        job_card_number = _value(extracted, "job_card_number")
        required = {
            "jobCardNumber": job_card_number,
            "householdOrMemberName": (
                _value(extracted, "head_of_household") or member_names
            ),
            "location": (
                _value(extracted, "village")
                or _value(extracted, "gram_panchayat")
                or _value(extracted, "district")
                or _value(extracted, "address")
            ),
        }
        identifier_valid = bool(
            job_card_number and is_valid_nrega_job_card(job_card_number)
        )
        warnings = (
            ["IDENTIFIER_FORMAT_ONLY_NOT_AUTHENTICITY"]
            if identifier_valid
            else []
        )
    elif document_type == "npr_letter":
        required = {
            "name": _value(extracted, "name"),
            "address": _value(extracted, "address"),
        }


        identifier_valid = None
        warnings = ["IDENTIFIER_NOT_OFFLINE_VERIFIABLE"]
    else:
        return KycExtractionAssessment(
            complete=False,
            confidence=0.0,
            identifier_valid=False,
            errors=["UNSUPPORTED_KYC_DOCUMENT_TYPE"],
        )

    assessment = _build_assessment(required, identifier_valid, regions, warnings)
    return _apply_semantic_checks(document_type, extracted, assessment)


def _assess_aadhaar(
    extracted: Any,
    regions: list[TextRegion],
) -> KycExtractionAssessment:
    number = _value(extracted, "aadhaar_number")
    masked = bool(_value(extracted, "aadhaar_masked"))
    last4 = _value(extracted, "aadhaar_last4")
    identifier_present = number or (masked and last4)


    address = _value(extracted, "address")
    pincode = _value(extracted, "pincode")
    has_front_demographics = bool(
        _value(extracted, "name")
        or _value(extracted, "date_of_birth")
        or _value(extracted, "year_of_birth")
        or _value(extracted, "gender")
    )

    if (address or pincode) and not has_front_demographics:
        required = {
            "aadhaarNumberOrMaskedLast4": identifier_present,
            "address": address,
            "pincode": pincode,
        }
    else:
        required = {
            "aadhaarNumberOrMaskedLast4": identifier_present,
            "name": _value(extracted, "name"),
            "dateOrYearOfBirth": (
                _value(extracted, "date_of_birth")
                or _value(extracted, "year_of_birth")
            ),
            "gender": _value(extracted, "gender"),
        }

    warnings: list[str] = []
    if number:
        identifier_valid: Optional[bool] = is_valid_aadhaar(number)
    elif masked and last4:
        identifier_valid = None
        warnings.append("MASKED_AADHAAR_CHECKSUM_UNAVAILABLE")
    else:
        identifier_valid = False

    assessment = _build_assessment(required, identifier_valid, regions, warnings)
    return _apply_semantic_checks("aadhaar", extracted, assessment)


def _build_assessment(
    required: dict[str, Any],
    identifier_valid: Optional[bool],
    regions: list[TextRegion],
    warnings: list[str],
) -> KycExtractionAssessment:
    missing = [name for name, value in required.items() if not _present(value)]
    completeness = (len(required) - len(missing)) / len(required) if required else 0.0
    geometry_confidences = _ocr_geometry_confidences(regions)
    ocr_confidence = (
        fmean(geometry_confidences)
        if geometry_confidences
        else 0.0
    )
    minimum_ocr_confidence = (
        min(geometry_confidences)
        if geometry_confidences
        else 0.0
    )
    if identifier_valid is True:
        identifier_score = 1.0
    elif identifier_valid is None:
        identifier_score = 0.6
    else:
        identifier_score = 0.0

    confidence = (
        (0.5 * completeness)
        + (0.3 * identifier_score)
        + (0.2 * ocr_confidence)
    )
    errors: list[str] = []

    if identifier_valid is False:
        errors.append("INVALID_OR_MISSING_DOCUMENT_IDENTIFIER")
        confidence = min(confidence, 0.39)
    if missing:
        errors.append("MISSING_REQUIRED_FIELDS")
        confidence = min(confidence, 0.69)
    if minimum_ocr_confidence < MIN_OCR_GEOMETRY_CONFIDENCE_FOR_SUCCESS:
        errors.append("LOW_OCR_CONFIDENCE")
        confidence = min(confidence, 0.49)

    complete = (
        not missing
        and identifier_valid is not False
        and minimum_ocr_confidence
        >= MIN_OCR_GEOMETRY_CONFIDENCE_FOR_SUCCESS
    )
    return KycExtractionAssessment(
        complete=complete,
        confidence=round(max(0.0, min(confidence, 1.0)), 3),
        identifier_valid=identifier_valid,
        missing_required_fields=missing,
        errors=errors,
        warnings=warnings,
    )


def _ocr_geometry_confidences(regions: list[TextRegion]) -> list[float]:




    confidence_by_geometry: dict[tuple[tuple[int, int], ...], float] = {}
    for region in regions:
        geometry = tuple(tuple(point) for point in region.bbox)
        score = max(0.0, min(float(region.confidence), 1.0))
        confidence_by_geometry[geometry] = max(
            score,
            confidence_by_geometry.get(geometry, 0.0),
        )
    return list(confidence_by_geometry.values())


def _apply_semantic_checks(
    document_type: str,
    extracted: Any,
    assessment: KycExtractionAssessment,
) -> KycExtractionAssessment:
    semantic_errors: list[str] = []

    if document_type == "pan":
        _require_past_date(
            _value(extracted, "date_of_birth"),
            "INVALID_DATE_OF_BIRTH",
            semantic_errors,
        )
    elif document_type == "aadhaar":
        dob = _value(extracted, "date_of_birth")
        yob = _value(extracted, "year_of_birth")
        if dob:
            _require_past_date(dob, "INVALID_DATE_OF_BIRTH", semantic_errors)
        elif yob:
            try:
                year = int(yob)
            except (TypeError, ValueError):
                semantic_errors.append("INVALID_YEAR_OF_BIRTH")
            else:
                if not 1900 <= year <= date.today().year:
                    semantic_errors.append("INVALID_YEAR_OF_BIRTH")
    elif document_type == "driving_licence":
        dob = _parse_printed_date(_value(extracted, "date_of_birth"))
        issue = _parse_printed_date(_value(extracted, "issue_date"))
        validity = _parse_printed_date(_value(extracted, "validity_date"))
        if dob is None:
            semantic_errors.append("INVALID_DATE_OF_BIRTH")
        if issue is None:
            semantic_errors.append("INVALID_ISSUE_DATE")
        if validity is None:
            semantic_errors.append("INVALID_VALIDITY_DATE")
        if issue and issue > date.today():
            semantic_errors.append("INVALID_ISSUE_DATE")
        if dob and issue and dob >= issue:
            semantic_errors.append("INVALID_DL_DATE_CHRONOLOGY")
        if issue and validity and issue >= validity:
            semantic_errors.append("INVALID_DL_DATE_CHRONOLOGY")
    elif document_type == "voter_id":
        dob = _value(extracted, "date_of_birth")
        age = _value(extracted, "age")
        if dob:
            _require_past_date(dob, "INVALID_DATE_OF_BIRTH", semantic_errors)
        elif age:
            try:
                age_number = int(age)
            except (TypeError, ValueError):
                semantic_errors.append("INVALID_AGE")
            else:
                if not 18 <= age_number <= 130:
                    semantic_errors.append("INVALID_AGE")
    elif document_type == "nrega_job_card":
        for value, error in (
            (_value(extracted, "registration_date"), "INVALID_REGISTRATION_DATE"),
            (_value(extracted, "validity_from"), "INVALID_VALIDITY_FROM"),
            (_value(extracted, "validity_to"), "INVALID_VALIDITY_TO"),
        ):
            if value and _parse_printed_date(value) is None:
                semantic_errors.append(error)
        registration = _parse_printed_date(
            _value(extracted, "registration_date")
        )
        if registration and registration > date.today():
            semantic_errors.append("INVALID_REGISTRATION_DATE")
        valid_from = _parse_printed_date(_value(extracted, "validity_from"))
        valid_to = _parse_printed_date(_value(extracted, "validity_to"))
        if valid_from and valid_to and valid_from >= valid_to:
            semantic_errors.append("INVALID_NREGA_VALIDITY_CHRONOLOGY")
    elif document_type == "npr_letter":
        issue_date = _value(extracted, "issue_date")
        if issue_date:
            _require_not_future_date(
                issue_date,
                "INVALID_ISSUE_DATE",
                semantic_errors,
            )
        pincode = _value(extracted, "pincode")
        if pincode and not (
            isinstance(pincode, str)
            and len(pincode) == 6
            and pincode.isdigit()
            and not pincode.startswith("0")
        ):
            semantic_errors.append("INVALID_PINCODE")

    if semantic_errors:
        assessment.complete = False
        assessment.confidence = min(assessment.confidence, 0.49)
        assessment.errors.extend(
            error for error in semantic_errors if error not in assessment.errors
        )
    return assessment


def _require_past_date(
    value: Any,
    error: str,
    errors: list[str],
) -> None:
    parsed = _parse_printed_date(value)
    if parsed is None or parsed >= date.today():
        errors.append(error)


def _require_not_future_date(
    value: Any,
    error: str,
    errors: list[str],
) -> None:
    parsed = _parse_printed_date(value)
    if parsed is None or parsed > date.today():
        errors.append(error)


def _parse_printed_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalised = value.strip().replace("/", "-").replace(".", "-")
    for fmt in (
        "%d-%m-%Y",
        "%d-%m-%y",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(normalised, fmt).date()
        except ValueError:
            continue
    return None


def _value(obj: Any, name: str) -> Any:
    return getattr(obj, name, None)


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)
