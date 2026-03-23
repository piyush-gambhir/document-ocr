"""
Passport OCR pipeline — single entry point.

Orchestrates: preprocessing → OCR → MRZ parsing → validation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .mrz_parser import MRZResult, parse_mrz
from .ocr_engine import TextRegion, run_ocr
from .preprocessor import ImageQualityError, preprocess
from .validator import validate, find_visual_field, find_visual_value_near


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PassportFields:
    surname: Optional[str] = None
    given_names: Optional[str] = None
    full_name: Optional[str] = None
    passport_number: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None   # ISO 8601
    sex: Optional[str] = None             # M / F / X
    expiry_date: Optional[str] = None     # ISO 8601
    issue_date: Optional[str] = None      # from visual field only
    place_of_birth: Optional[str] = None  # from visual field only
    country_code: Optional[str] = None    # ISO 3166-1 alpha-3


@dataclass
class PassportScanResult:
    success: bool
    confidence: float                                    # 0.0 – 1.0
    fields: PassportFields
    mrz_raw: Optional[tuple[str, str]] = None
    mrz_valid: bool = False
    low_confidence: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    processing_ms: int = 0

    def to_dict(self) -> dict:
        """Return a camelCase dictionary representation."""
        return {
            "success": self.success,
            "confidence": self.confidence,
            "fields": {
                "surname": self.fields.surname,
                "givenNames": self.fields.given_names,
                "fullName": self.fields.full_name,
                "passportNumber": self.fields.passport_number,
                "nationality": self.fields.nationality,
                "dateOfBirth": self.fields.date_of_birth,
                "sex": self.fields.sex,
                "expiryDate": self.fields.expiry_date,
                "issueDate": self.fields.issue_date,
                "placeOfBirth": self.fields.place_of_birth,
                "countryCode": self.fields.country_code,
            },
            "mrzRaw": list(self.mrz_raw) if self.mrz_raw else None,
            "mrzValid": self.mrz_valid,
            "lowConfidence": self.low_confidence,
            "errors": self.errors,
            "warnings": self.warnings,
            "processingMs": self.processing_ms,
        }


# ---------------------------------------------------------------------------
# Visual field extraction helper
# ---------------------------------------------------------------------------

def _extract_visual_field(
    regions: list[TextRegion],
    labels: list[str],
) -> Optional[str]:
    """Find a label in OCR regions and return the value below it."""
    label_region = find_visual_field(regions, labels)
    if label_region is None:
        return None
    value_region = find_visual_value_near(regions, label_region)
    if value_region is None:
        return None
    return value_region.text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan(image_input: Union[str, bytes, Path]) -> PassportScanResult:
    """
    Run the full passport OCR pipeline.

    Args:
        image_input: File path (str/Path), or raw image bytes.

    Returns:
        PassportScanResult with extracted fields, confidence, and diagnostics.
    """
    start = time.monotonic()
    all_errors: list[str] = []
    all_warnings: list[str] = []

    # 1. Preprocess
    try:
        prep = preprocess(image_input)
        all_warnings.extend(prep.warnings)
    except ImageQualityError as e:
        return PassportScanResult(
            success=False,
            confidence=0.0,
            fields=PassportFields(),
            errors=[str(e)],
            processing_ms=int((time.monotonic() - start) * 1000),
        )

    # 2. OCR
    regions = run_ocr(prep.image)

    if not regions:
        return PassportScanResult(
            success=False,
            confidence=0.0,
            fields=PassportFields(),
            errors=["NO_TEXT_DETECTED"],
            processing_ms=int((time.monotonic() - start) * 1000),
        )

    # 3. MRZ parsing
    mrz = parse_mrz(regions)
    mrz_valid = mrz.overall_checksum_valid if mrz else False

    if mrz and mrz.errors:
        all_warnings.extend(mrz.errors)

    if mrz is None:
        all_warnings.append("MRZ_NOT_DETECTED")

    # 4. Validation
    validation = validate(mrz, regions)
    all_errors.extend(validation.errors)
    all_warnings.extend(validation.warnings)

    # 5. Build fields — MRZ is ground truth when checksums pass
    fields = PassportFields()

    if mrz and mrz_valid:
        fields.surname = mrz.surname.value
        fields.given_names = mrz.given_names.value
        fields.passport_number = mrz.passport_number.value
        fields.nationality = mrz.nationality.value
        fields.date_of_birth = mrz.date_of_birth.value
        fields.sex = mrz.sex.value
        fields.expiry_date = mrz.expiry_date.value
        fields.country_code = mrz.country_code.value
    elif mrz:
        # MRZ detected but checksums failed — use values but flag
        fields.surname = mrz.surname.value
        fields.given_names = mrz.given_names.value
        fields.passport_number = mrz.passport_number.value
        fields.nationality = mrz.nationality.value
        fields.date_of_birth = mrz.date_of_birth.value
        fields.sex = mrz.sex.value
        fields.expiry_date = mrz.expiry_date.value
        fields.country_code = mrz.country_code.value

    # Full name
    if fields.surname and fields.given_names:
        fields.full_name = f"{fields.given_names} {fields.surname}"
    elif fields.surname:
        fields.full_name = fields.surname

    # Visual-only fields (not in MRZ)
    fields.issue_date = _extract_visual_field(
        regions, ["DATE OF ISSUE", "ISSUE DATE", "ISSUED", "DÉLIVRANCE"]
    )
    fields.place_of_birth = _extract_visual_field(
        regions, ["PLACE OF BIRTH", "BIRTHPLACE", "LIEU DE NAISSANCE"]
    )

    # Determine success
    low_confidence = (0.3 <= validation.confidence < 0.7)
    success = (
        fields.passport_number is not None
        and fields.surname is not None
        and validation.confidence >= 0.7
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return PassportScanResult(
        success=success,
        confidence=validation.confidence,
        fields=fields,
        mrz_raw=mrz.raw_lines if mrz else None,
        mrz_valid=mrz_valid,
        low_confidence=low_confidence,
        errors=all_errors,
        warnings=all_warnings,
        processing_ms=elapsed_ms,
    )
