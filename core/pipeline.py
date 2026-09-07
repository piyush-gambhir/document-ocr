"""
Passport OCR pipeline — single entry point.

Orchestrates: preprocessing → page classification → targeted OCR →
MRZ parsing → validation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Optional, Union

from .aadhaar_extractor import AadhaarFields, extract_aadhaar
from .back_page_extractor import BackPageFields, extract_back_page
from .document_classifier import classify_document
from .driving_licence_extractor import DrivingLicenceFields, extract_driving_licence
from .kyc_ocr import run_kyc_ocr
from .kyc_validation import (
    MIN_OCR_GEOMETRY_CONFIDENCE_FOR_SUCCESS,
    assess_kyc_extraction,
)
from .mrz_parser import MRZResult, parse_mrz
from .mrz_recovery import recover_passport_mrz
from .npr_extractor import NprLetterFields, extract_npr_letter
from .nrega_extractor import NregaFields, extract_nrega
from .ocr_engine import TextRegion, run_ocr
from .page_classifier import classify_passport_page
from .pan_extractor import PanFields, extract_pan
from .preprocessor import ImageQualityError, PreprocessResult, preprocess
from .document_registry import validate_document_hint
from .barcodes import decode_barcodes
from .document_input import input_bytes, pdf_pages
from .evidence import document_fields as collect_fields, field_evidence as collect_evidence
from .validator import validate, find_visual_field, find_visual_value_near
from .voter_id_extractor import VoterIdFields, extract_voter_id

TARGETED_CROP_TOP_RATIO = 0.45


@dataclass
class PassportFields:
    surname: Optional[str] = None
    given_names: Optional[str] = None
    full_name: Optional[str] = None
    passport_number: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None
    sex: Optional[str] = None
    expiry_date: Optional[str] = None
    issue_date: Optional[str] = None
    place_of_birth: Optional[str] = None
    country_code: Optional[str] = None


@dataclass
class DocumentScanResult:
    status: str
    document_type: str
    page_type: str
    confidence: float
    fields: Optional[PassportFields] = None
    back_page_fields: Optional[BackPageFields] = None
    pan_fields: Optional[PanFields] = None
    aadhaar_fields: Optional[AadhaarFields] = None
    driving_licence_fields: Optional[DrivingLicenceFields] = None
    voter_id_fields: Optional[VoterIdFields] = None
    nrega_job_card_fields: Optional[NregaFields] = None
    npr_letter_fields: Optional[NprLetterFields] = None
    mrz_raw: Optional[tuple[str, str]] = None
    mrz_valid: bool = False
    low_confidence: bool = False
    unsupported_reason: Optional[str] = None
    identifier_valid: Optional[bool] = None
    missing_required_fields: list[str] = field(default_factory=list)
    probe_text: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    processing_ms: int = 0

    document_fields: Optional[dict] = None
    issuing_country: Optional[str] = None
    issuing_region: Optional[str] = None
    field_evidence: Optional[dict] = None
    checks: Optional[dict] = None
    image_size: Optional[list[int]] = None

    def to_dict(self) -> dict:
        result = {
            "status": self.status,
            "documentType": self.document_type,
            "pageType": self.page_type,
            "confidence": self.confidence,
            "fields": _dataclass_to_camel_dict(self.fields),
            "backPageFields": _dataclass_to_camel_dict(self.back_page_fields),
            "panFields": _dataclass_to_camel_dict(self.pan_fields),
            "aadhaarFields": _dataclass_to_camel_dict(self.aadhaar_fields),
            "drivingLicenceFields": _dataclass_to_camel_dict(self.driving_licence_fields),
            "voterIdFields": _dataclass_to_camel_dict(self.voter_id_fields),
            "nregaJobCardFields": _dataclass_to_camel_dict(self.nrega_job_card_fields),
            "nprLetterFields": _dataclass_to_camel_dict(self.npr_letter_fields),
            "mrzRaw": list(self.mrz_raw) if self.mrz_raw else None,
            "mrzValid": self.mrz_valid,
            "lowConfidence": self.low_confidence,
            "unsupportedReason": self.unsupported_reason,
            "identifierValid": self.identifier_valid,
            "missingRequiredFields": [_snake_to_camel(name) for name in self.missing_required_fields],
            "probeText": self.probe_text,
            "errors": self.errors,
            "warnings": self.warnings,
            "processingMs": self.processing_ms,
        }
        if self.document_fields is not None:
            result.update({
                "schemaVersion": 1,
                "documentFields": {_snake_to_camel(k): _serialise_dataclass_value(v) for k, v in self.document_fields.items()},
                "issuingCountry": self.issuing_country,
                "issuingRegion": self.issuing_region,
                "checks": {_snake_to_camel(k): v for k, v in (self.checks or {}).items()},
            })
        if self.field_evidence is not None:
            result["fieldEvidence"] = {_snake_to_camel(k): v for k, v in self.field_evidence.items()}
            result["imageSize"] = self.image_size
        return result


def scan(
    image_input: Union[str, bytes, Path], *, document_type: str | None = None,
    country: str | None = None, include_evidence: bool = False,
) -> DocumentScanResult:
    """Scan one image/PDF page. Use scan_document for grouped images/all PDF pages.

    Hints restrict routing; they never make an unidentified document valid.
    Evidence coordinates refer to the normalized image from preview_image().
    """
    document_type, country = validate_document_hint(document_type, country)
    start = time.monotonic()
    try:
        data = input_bytes(image_input)
        if data.startswith(b"%PDF-"):
            page = pdf_pages(data, first_only=True)[0]
            warnings = ["PDF_ADDITIONAL_PAGES_IGNORED"] if page.total > 1 else []
            prep = PreprocessResult(page.image, warnings)
            return _scan_page(prep, start, document_type, country, include_evidence, native=page.regions)
        prep = preprocess(image_input)
    except ImageQualityError as exc:
        return DocumentScanResult("failure", "unknown", "unknown", 0.0,
                                  errors=[str(exc)], processing_ms=_elapsed_ms(start))
    return _scan_page(prep, start, document_type, country, include_evidence)


def preview_image(image_input: Union[str, bytes, Path]):
    """Return the exact coordinate plane used for first-page extraction evidence."""
    data = input_bytes(image_input)
    if data.startswith(b"%PDF-"):
        return pdf_pages(data, first_only=True)[0].image
    return preprocess(image_input).image


def _structured(regions, prep, start, *, document_type=None, country=None, barcodes=None):
    from .structured_documents import extract_structured_document
    extraction = extract_structured_document(regions, document_type=document_type,
                                             country=country, barcodes=barcodes)
    if extraction is None:
        return None
    return DocumentScanResult(
        "success" if extraction.complete else "failure", extraction.document_type,
        extraction.document_type, extraction.confidence,
        document_fields=extraction.fields, issuing_country=extraction.issuing_country,
        issuing_region=extraction.issuing_region, field_evidence=extraction.field_evidence,
        checks=extraction.checks, missing_required_fields=extraction.missing_required_fields,
        errors=extraction.errors, warnings=prep.warnings + extraction.warnings,
        processing_ms=_elapsed_ms(start),
    )


def _scan_page(prep, start, document_type, country, include_evidence, *, native=None):
    barcodes = decode_barcodes(prep.image)
    full = None
    source = "ocr"
    # Native text avoids re-OCR of digital forms and preserves exact characters.
    # A document that cannot be identified from it falls back to visible OCR.
    if native and sum(len(r.text) for r in native) >= 30:
        full = native
        source = "pdf_text"
        prep.warnings.append("PDF_NATIVE_TEXT_NOT_VISUALLY_VERIFIED")
    needs_full = bool(full or barcodes or document_type or country or include_evidence)
    if needs_full:
        full = full if full is not None else recover_passport_mrz(prep.image, run_kyc_ocr(prep.image), run_ocr)
        result = _structured(full, prep, start, document_type=document_type, country=country, barcodes=barcodes)
        if result is None:
            result = _scan_non_passport(prep, start, full_regions=full, try_structured=False)
        if source == "pdf_text" and (result.document_type == "unknown" or "DOCUMENT_TYPE_NOT_CONFIRMED" in result.errors):
            full = recover_passport_mrz(prep.image, run_kyc_ocr(prep.image), run_ocr)
            source = "ocr"
            result = _structured(full, prep, start, document_type=document_type, country=country, barcodes=barcodes)
            if result is None:
                result = _scan_non_passport(prep, start, full_regions=full, try_structured=False)
    else:
        result = _scan_prepared(prep, start)
    if result.issuing_country is None:
        if result.document_type in _NON_PASSPORT_EXTRACTORS:
            result.issuing_country = "IN"
        elif result.fields and result.fields.country_code:
            from .document_registry import normalize_country
            try:
                result.issuing_country = normalize_country(result.fields.country_code)
            except ValueError:
                pass
    if document_type and result.document_type != document_type:
        result.status = "failure"
        result.errors.append("DOCUMENT_TYPE_MISMATCH")
    if country and result.issuing_country and result.issuing_country != country:
        result.status = "failure"
        result.errors.append("DOCUMENT_COUNTRY_MISMATCH")
    if country and not result.issuing_country:
        result.status = "failure"
        result.errors.append("ISSUING_COUNTRY_UNRESOLVED")
    if include_evidence or document_type or country or result.document_fields is not None:
        result.document_fields = collect_fields(result)
        if include_evidence:
            if result.field_evidence is None:
                result.field_evidence = collect_evidence(result.document_fields, full or [], source=source, mrz_raw=result.mrz_raw)
            elif source == "pdf_text":
                for items in result.field_evidence.values():
                    for item in items:
                        if item["source"] == "ocr":
                            item["source"] = source
            result.image_size = [prep.image.shape[1], prep.image.shape[0]]
        else:
            result.field_evidence = None
    result.processing_ms = _elapsed_ms(start)
    return result


def _scan_prepared(prep, start):
    regions = _extract_targeted_regions(prep.image)
    if not regions:
        # The cheap probe uses a bottom crop. A non-passport document can have
        # all useful text elsewhere, especially with an explicitly configured
        # Indic recognition model. Confirm a strongly identified KYC document
        # from the full page before preserving the existing no-text failure.
        full_kyc_regions = recover_passport_mrz(prep.image, run_kyc_ocr(prep.image), run_ocr)
        if full_kyc_regions:
            structured = _structured(full_kyc_regions, prep, start)
            if structured is not None:
                return structured
            full_kyc_cls = classify_document(full_kyc_regions)
            if full_kyc_cls.document_type == "passport":
                page = classify_passport_page(full_kyc_regions)
                if page.page_type in {"passport_biodata", "passport_non_biodata"}:
                    return _scan_passport(
                        prep, page, full_kyc_regions, start,
                        full_page_regions=full_kyc_regions,
                    )
            if _is_strong_non_passport_classification(full_kyc_cls):
                return _scan_non_passport(
                    prep,
                    start,
                    full_regions=full_kyc_regions,
                    doc_cls=full_kyc_cls,
                )
        return DocumentScanResult(
            status="failure",
            document_type="unknown",
            page_type="unknown",
            confidence=0.0,
            errors=["NO_TEXT_DETECTED"],
            warnings=prep.warnings,
            processing_ms=_elapsed_ms(start),
        )

    classification = classify_passport_page(regions)
    if classification.page_type not in {"passport_biodata", "passport_non_biodata"}:
        return _scan_non_passport(prep, start)
    return _scan_passport(prep, classification, regions, start)


def _scan_passport(prep, classification, regions, start, *, full_page_regions=None):
    # The crop establishes routing; the full page supplies visual fields and
    # cross-checks even when the cropped MRZ already has valid check digits.
    if full_page_regions is None:
        full_page_regions = recover_passport_mrz(prep.image, run_ocr(prep.image), run_ocr)
    structured = _structured(full_page_regions, prep, start)
    if structured is not None:
        return structured
    if classification.page_type == "passport_non_biodata":
        back_fields = extract_back_page(full_page_regions)
        has_fields = any(
            getattr(back_fields, item.name)
            for item in dataclass_fields(back_fields)
        )
        return DocumentScanResult(
            status="success" if has_fields else "failure",
            document_type="passport",
            page_type="passport_non_biodata",
            confidence=classification.confidence if has_fields else 0.0,
            back_page_fields=back_fields,
            errors=[] if has_fields else ["NO_BACK_PAGE_FIELDS_DETECTED"],
            probe_text=classification.probe_text,
            warnings=prep.warnings + classification.reasons,
            processing_ms=_elapsed_ms(start),
        )

    mrz = parse_mrz(regions)
    if full_page_regions:
        fallback_mrz = parse_mrz(full_page_regions)
        if _candidate_score(fallback_mrz, full_page_regions) > _candidate_score(
            mrz, full_page_regions
        ):
            mrz = fallback_mrz
        regions = full_page_regions

    validation = validate(mrz, regions)
    fields = _build_fields(mrz, regions)

    mrz_valid = mrz.overall_checksum_valid if mrz else False
    all_warnings = prep.warnings.copy()
    all_errors = validation.errors.copy()

    if mrz and mrz.errors:
        all_warnings.extend(mrz.errors)
    elif mrz is None:
        all_warnings.append("MRZ_NOT_DETECTED")

    all_warnings.extend(validation.warnings)

    overall_confidence = round(
        min(max((validation.confidence * 0.85) + (classification.confidence * 0.15), 0.0), 1.0),
        3,
    )
    low_confidence = 0.3 <= overall_confidence < 0.7

    if (
        mrz_valid
        and not all_errors
        and fields.passport_number
        and fields.surname
        and overall_confidence >= 0.7
    ):
        return DocumentScanResult(
            status="success",
            document_type="passport",
            page_type="passport_biodata",
            confidence=overall_confidence,
            fields=fields,
            mrz_raw=mrz.raw_lines if mrz else None,
            mrz_valid=mrz_valid,
            low_confidence=low_confidence,
            probe_text=classification.probe_text,
            errors=all_errors,
            warnings=all_warnings,
            processing_ms=_elapsed_ms(start),
        )

    return DocumentScanResult(
        status="failure",
        document_type="passport",
        page_type="passport_biodata",
        confidence=overall_confidence,
        fields=fields if _has_meaningful_fields(fields) else None,
        mrz_raw=mrz.raw_lines if mrz else None,
        mrz_valid=mrz_valid,
        low_confidence=low_confidence,
        probe_text=classification.probe_text,
        errors=all_errors or ["LOW_CONFIDENCE_EXTRACTION"],
        warnings=all_warnings,
        processing_ms=_elapsed_ms(start),
    )


# Maps a classified document type to (result attribute, extractor function).
_NON_PASSPORT_EXTRACTORS = {
    "pan": ("pan_fields", extract_pan),
    "aadhaar": ("aadhaar_fields", extract_aadhaar),
    "driving_licence": ("driving_licence_fields", extract_driving_licence),
    "voter_id": ("voter_id_fields", extract_voter_id),
    "nrega_job_card": ("nrega_job_card_fields", extract_nrega),
    "npr_letter": ("npr_letter_fields", extract_npr_letter),
}

_STRONG_NON_PASSPORT_REASON_PREFIXES = {
    "pan": ("PAN_KEYWORDS_",),
    "aadhaar": ("AADHAAR_KEYWORDS_",),
    "driving_licence": ("DL_KEYWORDS_",),
    "voter_id": ("VOTER_KEYWORDS_",),
    "nrega_job_card": ("NREGA_",),
    "npr_letter": ("NPR_",),
}


def _is_strong_non_passport_classification(classification) -> bool:
    prefixes = _STRONG_NON_PASSPORT_REASON_PREFIXES.get(
        classification.document_type
    )
    return bool(
        prefixes
        and classification.confidence >= 0.86
        and any(
            reason.startswith(prefixes)
            for reason in classification.reasons
        )
    )


def _scan_non_passport(
    prep,
    start: float,
    *,
    full_regions=None,
    doc_cls=None,
    try_structured=True,
) -> DocumentScanResult:
    """Classify and extract a non-passport KYC document from full-page OCR."""
    if full_regions is None:
        full_regions = recover_passport_mrz(prep.image, run_kyc_ocr(prep.image), run_ocr)
    if not full_regions:
        return DocumentScanResult(
            status="failure",
            document_type="unknown",
            page_type="unknown",
            confidence=0.0,
            errors=["NO_TEXT_DETECTED"],
            warnings=prep.warnings,
            processing_ms=_elapsed_ms(start),
        )

    if try_structured:
        structured = _structured(full_regions, prep, start)
        if structured is not None:
            return structured
    if doc_cls is None:
        doc_cls = classify_document(full_regions)
    if doc_cls.document_type == "passport":
        page = classify_passport_page(full_regions)
        if page.page_type in {"passport_biodata", "passport_non_biodata"}:
            return _scan_passport(
                prep, page, full_regions, start, full_page_regions=full_regions
            )
    extractor_entry = _NON_PASSPORT_EXTRACTORS.get(doc_cls.document_type)

    if extractor_entry is None:
        # Passport missed by the cheap probe, or an unsupported/unknown document.
        return DocumentScanResult(
            status="unsupported_page",
            document_type=doc_cls.document_type,
            page_type="unknown",
            confidence=doc_cls.confidence,
            unsupported_reason="UNSUPPORTED_DOCUMENT",
            probe_text=[],
            warnings=prep.warnings + doc_cls.reasons,
            processing_ms=_elapsed_ms(start),
        )

    attr, extractor_fn = extractor_entry
    trusted_regions = [
        region
        for region in full_regions
        if region.confidence >= MIN_OCR_GEOMETRY_CONFIDENCE_FOR_SUCCESS
    ]
    fields = extractor_fn(trusted_regions)
    assessment = assess_kyc_extraction(
        doc_cls.document_type,
        fields,
        trusted_regions,
    )
    confidence = round(
        (doc_cls.confidence * 0.4) + (assessment.confidence * 0.6),
        3,
    )
    if not assessment.complete:
        confidence = min(confidence, 0.69)

    result = DocumentScanResult(
        status="success" if assessment.complete else "failure",
        document_type=doc_cls.document_type,
        page_type=doc_cls.document_type,
        confidence=confidence,
        low_confidence=0.3 <= confidence < 0.7,
        identifier_valid=assessment.identifier_valid,
        missing_required_fields=assessment.missing_required_fields,
        probe_text=[],
        errors=assessment.errors,
        warnings=prep.warnings + doc_cls.reasons + assessment.warnings,
        processing_ms=_elapsed_ms(start),
    )
    setattr(result, attr, fields)
    return result


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def _dataclass_to_camel_dict(obj) -> Optional[dict]:
    """Serialise a per-document field dataclass to a camelCase dict (or None)."""
    if obj is None:
        return None
    return {
        _snake_to_camel(f.name): _serialise_dataclass_value(getattr(obj, f.name))
        for f in dataclass_fields(obj)
    }


def _serialise_dataclass_value(value):
    """Recursively serialise nested extractor dataclasses and collections."""
    if hasattr(value, "__dataclass_fields__"):
        return _dataclass_to_camel_dict(value)
    if isinstance(value, list):
        return [_serialise_dataclass_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialise_dataclass_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _serialise_dataclass_value(item)
            for key, item in value.items()
        }
    return value


def _extract_targeted_regions(image) -> list[TextRegion]:
    height = image.shape[0]
    crop_top = int(height * TARGETED_CROP_TOP_RATIO)
    if height <= crop_top:
        return []

    targeted_regions = run_ocr(image[crop_top:, :])
    return _offset_regions(targeted_regions, y_offset=crop_top)


def _offset_regions(regions: list[TextRegion], *, x_offset: int = 0, y_offset: int = 0) -> list[TextRegion]:
    offset_regions: list[TextRegion] = []
    for region in regions:
        bbox = [[point[0] + x_offset, point[1] + y_offset] for point in region.bbox]
        offset_regions.append(TextRegion(text=region.text, bbox=bbox, confidence=region.confidence))
    return offset_regions


def _candidate_score(mrz: Optional[MRZResult], regions: list[TextRegion]) -> tuple:
    # A checksum-valid reading must always outrank one that fails its checksum.
    return (
        bool(mrz and mrz.overall_checksum_valid),
        bool(mrz and "MRZ_NAME_PADDING_NOISE" not in mrz.errors),
        validate(mrz, regions).confidence,
        mrz is not None,
    )


def _has_meaningful_fields(fields: PassportFields) -> bool:
    return any(
        value is not None
        for value in (
            fields.surname,
            fields.given_names,
            fields.passport_number,
            fields.nationality,
            fields.date_of_birth,
            fields.expiry_date,
        )
    )


def _build_fields(
    mrz: Optional[MRZResult],
    regions: list[TextRegion],
) -> PassportFields:
    fields = PassportFields()

    if mrz:
        fields.surname = mrz.surname.value
        fields.given_names = mrz.given_names.value
        fields.passport_number = mrz.passport_number.value
        fields.nationality = mrz.nationality.value
        fields.date_of_birth = mrz.date_of_birth.value
        fields.sex = mrz.sex.value
        fields.expiry_date = mrz.expiry_date.value
        fields.country_code = mrz.country_code.value

    if fields.surname and fields.given_names:
        fields.full_name = f"{fields.given_names} {fields.surname}"
    elif fields.surname:
        fields.full_name = fields.surname

    fields.issue_date = _extract_visual_field(
        regions,
        ["DATE OF ISSUE", "ISSUE DATE", "ISSUED", "DÉLIVRANCE"],
    )
    fields.place_of_birth = _extract_visual_field(
        regions,
        ["PLACE OF BIRTH", "BIRTHPLACE", "LIEU DE NAISSANCE"],
    )
    return fields


def _extract_visual_field(
    regions: list[TextRegion],
    labels: list[str],
) -> Optional[str]:
    label_region = find_visual_field(regions, labels)
    if label_region is None:
        return None
    value_region = find_visual_value_near(regions, label_region)
    if value_region is None:
        return None
    return value_region.text.strip()
