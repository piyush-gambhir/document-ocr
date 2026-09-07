"""
Fast passport page classification.

Uses a lightweight OCR probe to distinguish passport biodata pages from
supplementary/non-biodata pages before the heavier extraction pipeline runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mrz_parser import _find_mrz_lines, parse_mrz
from .ocr_engine import TextRegion

_BIODATA_HINTS = [
    "SURNAME",
    "GIVEN NAME",
    "PASSPORT NO",
    "PASSPORT NUMBER",
    "DATE OF BIRTH",
    "NATIONALITY",
    "PLACE OF BIRTH",
    "DATE OF ISSUE",
    "DATE OF EXPIRY",
    "SEX",
    "COUNTRY CODE",
]

_NON_BIODATA_HINTS = [
    "NAME OF FATHER",
    "LEGAL GUARDIAN",
    "NAME OF MOTHER",
    "NAME OF SPOUSE",
    "ADDRESS",
    "FILE NO",
    "OLD PASSPORT",
    "PLACE OF ISSUE",
]


@dataclass
class PageClassification:
    document_type: str
    page_type: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    probe_text: list[str] = field(default_factory=list)


def classify_passport_page(regions: list[TextRegion]) -> PageClassification:
    """Classify a page using a low-cost OCR probe."""
    probe_text = [region.text.strip() for region in regions if region.text.strip()][:12]
    normalised_regions = [_normalise_text(region.text) for region in regions if region.text.strip()]

    has_mrz = _has_mrz_like_lines(regions)
    biodata_matches = _count_matches(normalised_regions, _BIODATA_HINTS)
    non_biodata_matches = _count_matches(normalised_regions, _NON_BIODATA_HINTS)

    if has_mrz or biodata_matches >= 2:
        confidence = 0.55 + (0.12 * min(biodata_matches, 3)) + (0.18 if has_mrz else 0.0)
        reasons = ["MRZ_DETECTED"] if has_mrz else []
        if biodata_matches:
            reasons.append(f"BIODATA_HINTS_{biodata_matches}")
        return PageClassification(
            document_type="passport",
            page_type="passport_biodata",
            confidence=round(min(confidence, 0.99), 3),
            reasons=reasons,
            probe_text=probe_text,
        )

    if non_biodata_matches >= 2:
        confidence = 0.62 + (0.1 * min(non_biodata_matches, 3))
        return PageClassification(
            document_type="passport",
            page_type="passport_non_biodata",
            confidence=round(min(confidence, 0.98), 3),
            reasons=[f"NON_BIODATA_HINTS_{non_biodata_matches}"],
            probe_text=probe_text,
        )

    if biodata_matches or non_biodata_matches:
        return PageClassification(
            document_type="passport",
            page_type="unknown",
            confidence=0.45,
            reasons=["WEAK_PASSPORT_HINTS"],
            probe_text=probe_text,
        )

    return PageClassification(
        document_type="unknown",
        page_type="unknown",
        confidence=0.2,
        reasons=["NO_PASSPORT_HINTS"],
        probe_text=probe_text,
    )


def _count_matches(normalised_regions: list[str], hints: list[str]) -> int:
    matched_hints: set[str] = set()
    for hint in hints:
        hint_text = _normalise_text(hint)
        padded_hint = f" {hint_text} "
        for region_text in normalised_regions:
            if padded_hint in f" {region_text} ":
                matched_hints.add(hint_text)
                break
    return len(matched_hints)


def _normalise_text(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_mrz_like_lines(regions: list[TextRegion]) -> bool:
    if not regions:
        return False

    page_bottom = max((max(point[1] for point in region.bbox) for region in regions if region.bbox), default=0)
    bottom_threshold = page_bottom * 0.6
    bottom_regions = [
        region for region in regions
        if region.bbox and max(point[1] for point in region.bbox) >= bottom_threshold
    ]
    # Optional data may occupy all of line two: it need not contain fillers.
    # Require a paired TD3 header instead of counting arbitrary long strings.
    if _find_mrz_lines(bottom_regions) is not None:
        return True
    # A passport may sit high in a larger photograph, with background text
    # below it. Strong MRZ evidence should not depend on its position in that
    # photograph. Keep checksum validation for this location-independent path.
    mrz = parse_mrz(regions)
    return bool(mrz and mrz.overall_checksum_valid)
