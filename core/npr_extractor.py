"""Conservative extractor for NPR name-and-address letters.

The Reserve Bank of India's KYC directions refer to a letter issued by the
National Population Register (NPR) that contains a person's name and address.
They do not define a single visual template or a universal reference-number
format for such letters.  This extractor therefore makes deliberately narrow
claims:

* It returns fields only when the OCR contains explicit NPR evidence.
* Personal data is read only from an adjacent, explicit field label.
* Reference numbers are preserved as printed; no checksum or standard format
  is claimed.
* Dates are surfaced only when tied to an issue/letter-date label.

This is text extraction, not proof that a letter is authentic or current.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ocr_engine import TextRegion
from .validator import find_visual_value_near, find_visual_value_right


_DATE_RE = re.compile(
    r"\b("
    r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"
    r"|\d{1,2}\s+(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?"
    r"|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?"
    r"|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)
_PINCODE_RE = re.compile(r"\b([1-9]\d{5})\b")

_REFERENCE_LABELS = (
    "REFERENCE NUMBER",
    "REFERENCE NO",
    "REF NUMBER",
    "REF NO",
    "LETTER NUMBER",
    "LETTER NO",
    "FILE NUMBER",
    "FILE NO",
)
_REFERENCE_HINDI_LABELS = ("संदर्भ संख्या", "पत्र संख्या")

_NAME_LABELS = (
    "NAME OF RESIDENT",
    "RESIDENT NAME",
    "NAME",
)
_NAME_HINDI_LABELS = ("निवासी का नाम", "नाम")

_ADDRESS_LABELS = (
    "ADDRESS OF RESIDENT",
    "RESIDENT ADDRESS",
    "POSTAL ADDRESS",
    "ADDRESS",
)
_ADDRESS_HINDI_LABELS = ("निवासी का पता", "पता")

_ISSUE_DATE_LABELS = (
    "DATE OF ISSUE",
    "ISSUE DATE",
    "LETTER DATE",
)
_ISSUE_DATE_HINDI_LABELS = ("जारी करने की तिथि", "दिनांक")

_PINCODE_LABELS = ("PIN CODE", "PINCODE", "POSTAL CODE")
_PINCODE_HINDI_LABELS = ("पिन कोड",)




_GENERIC_ENGLISH_LABELS = frozenset({"NAME", "ADDRESS"})
_GENERIC_HINDI_LABELS = frozenset({"नाम", "पता"})

_ALL_ENGLISH_LABELS = (
    *_REFERENCE_LABELS,
    *_NAME_LABELS,
    *_ADDRESS_LABELS,
    *_ISSUE_DATE_LABELS,
    *_PINCODE_LABELS,
)
_ALL_HINDI_LABELS = (
    *_REFERENCE_HINDI_LABELS,
    *_NAME_HINDI_LABELS,
    *_ADDRESS_HINDI_LABELS,
    *_ISSUE_DATE_HINDI_LABELS,
    *_PINCODE_HINDI_LABELS,
)

_ADDRESS_STOP_PHRASES = (
    "YOURS FAITHFULLY",
    "AUTHORISED SIGNATORY",
    "AUTHORIZED SIGNATORY",
    "SIGNATURE",
    "REGISTRAR GENERAL",
    "CENSUS COMMISSIONER",
    "TELEPHONE",
    "PHONE",
    "EMAIL",
    "WEBSITE",
)


@dataclass
class NprLetterFields:
    """Fields conservatively recoverable from an NPR name/address letter."""

    reference_number: Optional[str] = None
    name: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    issue_date: Optional[str] = None


def _normalise_latin(text: str) -> str:
    text = text.upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_npr_evidence(regions: list[TextRegion]) -> bool:
    """Require an explicit NPR title, including its common Hindi rendering.

    The acronym ``NPR`` alone is accepted only when accompanied by the issuing
    authority (Registrar General / Census Commissioner).  This avoids treating
    unrelated letters or uses of the acronym as NPR identity documents.
    """
    joined = " ".join(region.text for region in regions if region.text.strip())
    normalised = _normalise_latin(joined)

    if "NATIONAL POPULATION REGISTER" in normalised:
        return True
    if "राष्ट्रीय जनसंख्या रजिस्टर" in joined:
        return True

    has_npr_token = bool(re.search(r"\bNPR\b", normalised))
    has_issuer = (
        "REGISTRAR GENERAL" in normalised
        or "CENSUS COMMISSIONER" in normalised
        or "महापंजीयक" in joined
        or "जनगणना आयुक्त" in joined
    )
    return has_npr_token and has_issuer


def _label_match_score(
    text: str,
    english_labels: tuple[str, ...],
    hindi_labels: tuple[str, ...],
) -> int:
    normalised = _normalise_latin(text)
    padded = f" {normalised} "
    raw_prefix = re.split(r"[:：]", text, maxsplit=1)[0]
    normalised_prefix = _normalise_latin(raw_prefix)
    best = 0

    for label in english_labels:
        if normalised_prefix == label and normalised != label:


            best = max(best, 30_000 + len(label))
        elif normalised == label:
            best = max(best, 20_000 + len(label))
        elif (
            label not in _GENERIC_ENGLISH_LABELS
            and f" {label} " in padded
        ):
            best = max(best, 10_000 + len(label))

    for label in hindi_labels:
        if raw_prefix.strip(" :.-/") == label and text.strip(" :.-/") != label:
            best = max(best, 30_000 + len(label))
        elif text.strip(" :.-/") == label:
            best = max(best, 20_000 + len(label))
        elif label not in _GENERIC_HINDI_LABELS and label in text:
            best = max(best, 10_000 + len(label))

    return best


def _find_label_region(
    regions: list[TextRegion],
    english_labels: tuple[str, ...],
    hindi_labels: tuple[str, ...] = (),
) -> Optional[TextRegion]:
    best: tuple[int, float, TextRegion] | None = None
    for region in regions:
        score = _label_match_score(region.text, english_labels, hindi_labels)
        if score == 0:
            continue
        candidate = (score, region.confidence, region)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


def _prefix_is_label(
    prefix: str,
    english_labels: tuple[str, ...],
    hindi_labels: tuple[str, ...],
) -> bool:
    return _label_match_score(prefix, english_labels, hindi_labels) > 0


def _inline_value(
    text: str,
    english_labels: tuple[str, ...],
    hindi_labels: tuple[str, ...] = (),
) -> Optional[str]:
    """Read ``Label: value`` without assuming a particular letter layout."""
    pieces = re.split(r"[:：]", text, maxsplit=1)
    if len(pieces) != 2:
        pieces = re.split(r"\s+[–—-]\s+", text, maxsplit=1)
    if len(pieces) != 2:
        return None
    prefix, value = pieces
    if not _prefix_is_label(prefix, english_labels, hindi_labels):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t:;,–—-")
    return cleaned or None


def _is_field_label(text: str) -> bool:
    prefix = re.split(r"[:：]", text, maxsplit=1)[0]
    return _label_match_score(
        prefix,
        _ALL_ENGLISH_LABELS,
        _ALL_HINDI_LABELS,
    ) > 0


def _clean_scalar(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip(" \t:;,–—-")
    if not cleaned or _is_field_label(cleaned):
        return None
    return cleaned


def _labelled_value(
    regions: list[TextRegion],
    english_labels: tuple[str, ...],
    hindi_labels: tuple[str, ...] = (),
) -> Optional[str]:
    label = _find_label_region(regions, english_labels, hindi_labels)
    if label is None:
        return None

    inline = _inline_value(label.text, english_labels, hindi_labels)
    if inline:
        return _clean_scalar(inline)

    value = find_visual_value_right(regions, label) or find_visual_value_near(
        regions, label
    )
    return _clean_scalar(value.text if value is not None else None)


def _extract_reference_number(regions: list[TextRegion]) -> Optional[str]:
    value = _labelled_value(
        regions,
        _REFERENCE_LABELS,
        _REFERENCE_HINDI_LABELS,
    )
    if value is None or len(value) > 80 or not any(ch.isalnum() for ch in value):
        return None
    return value


def _extract_name(regions: list[TextRegion]) -> Optional[str]:
    value = _labelled_value(regions, _NAME_LABELS, _NAME_HINDI_LABELS)
    if value is None or len(value) > 160:
        return None



    if not any(ch.isalpha() for ch in value):
        return None
    return value


def _top(region: TextRegion) -> int:
    return min(point[1] for point in region.bbox)


def _bottom(region: TextRegion) -> int:
    return max(point[1] for point in region.bbox)


def _left(region: TextRegion) -> int:
    return min(point[0] for point in region.bbox)


def _is_address_footer(text: str) -> bool:
    normalised = _normalise_latin(text)
    return any(phrase in normalised for phrase in _ADDRESS_STOP_PHRASES)


def _extract_address(regions: list[TextRegion]) -> Optional[str]:
    label = _find_label_region(regions, _ADDRESS_LABELS, _ADDRESS_HINDI_LABELS)
    if label is None:
        return None

    label_bottom = _bottom(label)
    label_left = _left(label)
    parts: list[str] = []
    used_regions: set[int] = set()

    inline = _inline_value(label.text, _ADDRESS_LABELS, _ADDRESS_HINDI_LABELS)
    if inline:
        parts.append(inline)

    right = find_visual_value_right(regions, label)
    if right is not None and not _is_field_label(right.text):
        cleaned = _clean_scalar(right.text)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
        used_regions.add(id(right))



    stop_y: Optional[int] = None
    for region in regions:
        if region is label or _top(region) < label_bottom - 4:
            continue
        if _is_field_label(region.text) or _is_address_footer(region.text):
            top = _top(region)
            if stop_y is None or top < stop_y:
                stop_y = top

    candidates = sorted(regions, key=lambda region: (_top(region), _left(region)))
    for region in candidates:
        if region is label or id(region) in used_regions:
            continue
        top = _top(region)
        if top < label_bottom - 4:
            continue
        if top - label_bottom > 320:
            break
        if stop_y is not None and top >= stop_y:
            break
        if abs(_left(region) - label_left) > 260:
            continue
        if _is_field_label(region.text) or _is_address_footer(region.text):
            break
        cleaned = _clean_scalar(region.text)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
        if len(parts) >= 7:
            break

    if not parts:
        return None
    return ", ".join(parts)


def _extract_issue_date(regions: list[TextRegion]) -> Optional[str]:
    value = _labelled_value(
        regions,
        _ISSUE_DATE_LABELS,
        _ISSUE_DATE_HINDI_LABELS,
    )
    if value is None:
        return None
    match = _DATE_RE.search(value)
    return match.group(1) if match else None


def _extract_pincode(
    regions: list[TextRegion],
    address: Optional[str],
) -> Optional[str]:
    if address:
        match = _PINCODE_RE.search(address)
        if match:
            return match.group(1)

    value = _labelled_value(regions, _PINCODE_LABELS, _PINCODE_HINDI_LABELS)
    if value:
        match = _PINCODE_RE.search(value)
        if match:
            return match.group(1)
    return None


def extract_npr_letter(regions: list[TextRegion]) -> NprLetterFields:
    """Extract labelled fields from an explicitly identified NPR letter.

    Empty or non-NPR OCR input returns an empty dataclass.  No field is inferred
    from reading order alone.
    """
    fields = NprLetterFields()
    if not regions or not _has_npr_evidence(regions):
        return fields

    fields.reference_number = _extract_reference_number(regions)
    fields.name = _extract_name(regions)
    fields.address = _extract_address(regions)
    fields.pincode = _extract_pincode(regions, fields.address)
    fields.issue_date = _extract_issue_date(regions)
    return fields
