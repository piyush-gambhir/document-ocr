"""
Document-type router.

Given OCR regions for a full document image, decides which supported document
type it is — passport, PAN, Aadhaar, driving licence, or voter ID — using a
combination of keyword hints and identifier-format signals. The pipeline calls
this only when the cheap passport probe (page_classifier) did not already
recognise a passport, and dispatches to the matching per-document extractor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ocr_engine import TextRegion
from .page_classifier import _has_mrz_like_lines, _normalise_text
from .validators import (
    normalize_dl,
    normalize_epic,
    normalize_pan,
    extract_aadhaar_number,
    is_valid_aadhaar,
)

# ---------------------------------------------------------------------------
# Keyword hints (normalised: upper-case, alphanumerics only). Deliberately
# avoid generic phrases like "GOVERNMENT OF INDIA" that appear on several docs.
# ---------------------------------------------------------------------------

_PAN_KEYWORDS = ["INCOME TAX DEPARTMENT", "PERMANENT ACCOUNT NUMBER", "INCOME TAX"]
_AADHAAR_KEYWORDS = [
    "AADHAAR", "AADHAR", "UNIQUE IDENTIFICATION", "UIDAI", "MERA AADHAAR",
    "ENROLLMENT NO", "VID",
]
_DL_KEYWORDS = [
    "DRIVING LICENCE", "DRIVING LICENSE", "TRANSPORT DEPARTMENT",
    "MOTOR VEHICLE", "FORM 7",
]
_VOTER_KEYWORDS = [
    "ELECTION COMMISSION", "ELECTORS PHOTO IDENTITY", "ELECTOR",
    "ELECTION", "IDENTITY CARD",
]
_PASSPORT_KEYWORDS = ["PASSPORT", "REPUBLIC OF INDIA PASSPORT"]

_SUPPORTED = {"passport", "pan", "aadhaar", "driving_licence", "voter_id"}


@dataclass
class DocumentClassification:
    document_type: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    probe_text: list[str] = field(default_factory=list)


def _count_keyword_matches(normalised_regions: list[str], keywords: list[str]) -> int:
    matched: set[str] = set()
    for keyword in keywords:
        norm_kw = _normalise_text(keyword)
        padded = f" {norm_kw} "
        for region_text in normalised_regions:
            if padded in f" {region_text} ":
                matched.add(norm_kw)
                break
    return len(matched)


def _any_token(regions: list[TextRegion], normalizer) -> bool:
    return any(normalizer(r.text) is not None for r in regions if r.text.strip())


def classify_document(regions: list[TextRegion]) -> DocumentClassification:
    """Classify a full-page document into one of the supported types."""
    probe_text = [r.text.strip() for r in regions if r.text.strip()][:15]
    normalised_regions = [_normalise_text(r.text) for r in regions if r.text.strip()]
    joined_raw = " ".join(r.text for r in regions if r.text.strip())

    # --- per-type evidence ---
    pan_kw = _count_keyword_matches(normalised_regions, _PAN_KEYWORDS)
    aadhaar_kw = _count_keyword_matches(normalised_regions, _AADHAAR_KEYWORDS)
    dl_kw = _count_keyword_matches(normalised_regions, _DL_KEYWORDS)
    voter_kw = _count_keyword_matches(normalised_regions, _VOTER_KEYWORDS)
    passport_kw = _count_keyword_matches(normalised_regions, _PASSPORT_KEYWORDS)

    has_pan = _any_token(regions, normalize_pan)
    aadhaar_number = extract_aadhaar_number(joined_raw)
    aadhaar_checksum_ok = is_valid_aadhaar(joined_raw)
    has_dl = _any_token(regions, normalize_dl)
    has_epic = _any_token(regions, normalize_epic)
    has_mrz = _has_mrz_like_lines(regions)

    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(doc: str, score: float, *why: str):
        scores[doc] = scores.get(doc, 0.0) + score
        reasons.setdefault(doc, []).extend(why)

    # Keyword weight: 2 per distinct phrase. Format/identifier weight: 3.
    if pan_kw:
        add("pan", 2 * pan_kw, f"PAN_KEYWORDS_{pan_kw}")
    if has_pan:
        add("pan", 3, "PAN_FORMAT")

    if aadhaar_kw:
        add("aadhaar", 2 * aadhaar_kw, f"AADHAAR_KEYWORDS_{aadhaar_kw}")
    if aadhaar_number:
        add("aadhaar", 3, "AADHAAR_NUMBER")
    if aadhaar_checksum_ok:
        add("aadhaar", 2, "AADHAAR_CHECKSUM_VALID")

    if dl_kw:
        add("driving_licence", 2 * dl_kw, f"DL_KEYWORDS_{dl_kw}")
    if has_dl:
        add("driving_licence", 3, "DL_FORMAT")

    if voter_kw:
        add("voter_id", 2 * voter_kw, f"VOTER_KEYWORDS_{voter_kw}")
    if has_epic:
        add("voter_id", 3, "EPIC_FORMAT")

    if passport_kw:
        add("passport", 2 * passport_kw, f"PASSPORT_KEYWORDS_{passport_kw}")
    if has_mrz:
        add("passport", 4, "MRZ_DETECTED")

    if not scores:
        return DocumentClassification("unknown", 0.2, ["NO_DOCUMENT_HINTS"], probe_text)

    best_doc = max(scores, key=lambda d: scores[d])
    best_score = scores[best_doc]

    # Need at least a keyword phrase or an identifier-format hit (score >= 2).
    if best_score < 2:
        return DocumentClassification("unknown", 0.3, ["WEAK_DOCUMENT_HINTS"], probe_text)

    confidence = round(min(0.5 + 0.12 * best_score, 0.98), 3)
    return DocumentClassification(
        document_type=best_doc,
        confidence=confidence,
        reasons=reasons.get(best_doc, []),
        probe_text=probe_text,
    )
