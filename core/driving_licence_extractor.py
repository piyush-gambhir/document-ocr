"""
Extractor for Indian Driving Licences (DL).

Fields: DL number, name, relation (S/D/W of), date of birth, date of issue,
validity date, address, blood group, class of vehicle (COV).

Indian DL layouts vary a great deal by issuing state/RTO and are frequently
bilingual (Hindi/English and regional scripts). Extraction is therefore
label- and format-driven rather than positional:

  * The DL number is recovered with ``core.validators.normalize_dl`` (state
    code + RTO + year + serial), tolerating spaces/hyphens and the common
    case where OCR splits the number across two adjacent regions.
  * A DL card carries several ``DD/MM/YYYY`` dates (DOB, issue, one or two
    validity dates).  Each date is assigned strictly by the label adjacent to
    it (right-then-below), never by raw reading order, so re-ordered or
    multi-column layouts do not scramble the fields.
  * When both a non-transport (NT) and a transport (TR) validity date are
    present, the non-transport / primary validity is preferred (see
    ``_find_validity_date``).
  * Addresses may be multi-line and may appear twice (Present + Permanent);
    the present/current address is preferred (see ``_find_address``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ocr_engine import TextRegion
from .validator import (
    find_label_value,
    find_visual_field,
    find_visual_value_near,
    find_visual_value_right,
)
from .validators import normalize_dl

# A DD/MM/YYYY-style date anywhere in a string (also tolerates 2-digit years
# and '.'/'-'/'/' separators that OCR emits interchangeably).
_DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b")

# Blood group as a standalone token, e.g. "B+", "O-", "AB+VE", "A POSITIVE".
# A trailing sign/word is REQUIRED so a bare "B" inside a label like "BG" or a
# word like "BIHAR" is not mistaken for a blood group.
_BLOOD_GROUP_RE = re.compile(
    r"\b(AB|A|B|O)\s*"
    r"(\+VE|-VE|\+|-|POS(?:ITIVE)?|NEG(?:ATIVE)?)"
    r"(?![A-Z])",
    re.IGNORECASE,
)
# Canonical class-of-vehicle tokens that appear on Indian DLs.
_COV_TOKENS = [
    "MCWOG", "MCWG", "MCEX50CC", "MGV", "HGMV", "HMV", "HPMV", "LMV-NT",
    "LMV-TR", "LMV", "TRANS", "TRACTOR", "ERIG", "ROAD ROLLER", "MC", "FVG",
    "PSV", "3WT", "3WNT", "INVCRG",
]

_NAME_LABELS = ["NAME", "HOLDER S NAME", "HOLDERS NAME", "HOLDER NAME"]
# S/D/W of => relation/guardian. Many OCRs collapse the slashes.
_RELATION_LABELS = [
    "SON DAUGHTER WIFE OF",
    "S D W OF",
    "S O",
    "D O",
    "W O",
    "C O",
    "SON OF",
    "DAUGHTER OF",
    "WIFE OF",
    "FATHER",
    "GUARDIAN",
]
_DOB_LABELS = ["DATE OF BIRTH", "DOB", "BIRTH"]
_DOI_LABELS = ["DATE OF ISSUE", "ISSUE DATE", "DOI", "ISSUE"]
# Generic validity labels (used when there is a single validity date).
_VALIDITY_LABELS = [
    "VALID TILL",
    "VALID UPTO",
    "VALID UNTIL",
    "VALIDITY",
    "DATE OF EXPIRY",
    "EXPIRY",
]
# Non-transport (primary) validity labels — preferred when both NT and TR exist.
_VALIDITY_NT_LABELS = [
    "VALIDITY NT",
    "VALID TILL NT",
    "NON TRANSPORT",
    "NT",
]
# Transport validity labels — only used if no NT/primary date is found.
_VALIDITY_TR_LABELS = [
    "VALIDITY TR",
    "VALID TILL TR",
    "TRANSPORT",
    "TR",
]
_BLOOD_GROUP_LABELS = ["BLOOD GROUP", "BG", "BLOOD"]
_COV_LABELS = [
    "CLASS OF VEHICLE",
    "CLASS OF VEHICLES",
    "COV",
    "CL OF VEH",
    "AUTHORISATION TO DRIVE",
    "AUTHORIZATION TO DRIVE",
]
# Present/current address preferred over permanent.
_PRESENT_ADDRESS_LABELS = [
    "PRESENT ADDRESS",
    "CURRENT ADDRESS",
    "TEMPORARY ADDRESS",
    "TEMP ADDRESS",
]
_PERMANENT_ADDRESS_LABELS = ["PERMANENT ADDRESS", "PERM ADDRESS"]
_GENERIC_ADDRESS_LABELS = ["ADDRESS", "ADD", "ADDR"]


@dataclass
class DrivingLicenceFields:
    dl_number: Optional[str] = None
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    issue_date: Optional[str] = None
    validity_date: Optional[str] = None
    address: Optional[str] = None
    # --- Added fields (must be synced to TS DrivingLicenceFields) ---
    relation_name: Optional[str] = None
    blood_group: Optional[str] = None
    class_of_vehicle: Optional[str] = None
    # Secondary (transport) validity date, when a card lists both NT and TR.
    validity_date_transport: Optional[str] = None


# ---------------------------------------------------------------------------
# DL number
# ---------------------------------------------------------------------------

def _find_dl_number(regions: list[TextRegion]) -> Optional[str]:
    """Recover the DL number, including the case where OCR splits it in two.

    First try a direct ``normalize_dl`` scan over each region (handles
    ``MH12 20110012345``, ``DL-0420110149646``, ``TN0120200001234`` …).  If
    that fails, try concatenating spatially adjacent regions on the same row,
    since some cards render the state/RTO prefix and the serial as separate
    OCR tokens (e.g. ``"MH12"`` then ``"20110012345"``).
    """
    for region in regions:
        dl = normalize_dl(region.text)
        if dl:
            return dl

    # Adjacency fallback: join same-row neighbours left-to-right and re-scan.
    ordered = sorted(
        regions,
        key=lambda r: (
            round(min(p[1] for p in r.bbox) / 20),  # row band
            min(p[0] for p in r.bbox),
        ),
    )
    for i, region in enumerate(ordered):
        top = min(p[1] for p in region.bbox)
        bottom = max(p[1] for p in region.bbox)
        height = max(bottom - top, 1)
        combined = region.text
        for nxt in ordered[i + 1 : i + 4]:
            n_top = min(p[1] for p in nxt.bbox)
            n_bottom = max(p[1] for p in nxt.bbox)
            overlap = min(bottom, n_bottom) - max(top, n_top)
            if overlap < height * 0.4:
                continue
            combined += " " + nxt.text
            dl = normalize_dl(combined)
            if dl:
                return dl
    return None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _first_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _DATE_RE.search(text)
    return m.group(1) if m else None


def _labelled_date(
    regions: list[TextRegion],
    labels: list[str],
    *,
    label_region: Optional[TextRegion] = None,
) -> Optional[str]:
    """Resolve a date by the label adjacent to it (right then below).

    The label's *own* text is also inspected: some compact layouts print the
    value on the same region as the label (``"DOB: 09/03/1986"``).
    """
    if label_region is None:
        label_region = find_visual_field(regions, labels)
    if label_region is None:
        return None

    # Date embedded in the label region itself.
    self_date = _first_date(label_region.text)
    if self_date:
        return self_date

    value = find_visual_value_right(regions, label_region) or find_visual_value_near(
        regions, label_region
    )
    if value is not None:
        return _first_date(value.text)
    return None


def _find_validity_date(regions: list[TextRegion]) -> tuple[Optional[str], Optional[str]]:
    """Return ``(primary_validity, transport_validity)``.

    Indian DLs may carry two validity dates: NT (non-transport) and TR
    (transport).  We prefer the non-transport / primary date for
    ``validity_date`` and expose the transport date separately.

    Resolution order for the primary date:
      1. An explicit non-transport (NT) label.
      2. A generic "Valid Till / Valid Upto / Validity" label.
    The transport date is taken from an explicit TR label when present.
    """
    nt_label = find_visual_field(regions, _VALIDITY_NT_LABELS)
    tr_label = find_visual_field(regions, _VALIDITY_TR_LABELS)
    generic_label = find_visual_field(regions, _VALIDITY_LABELS)

    transport = _labelled_date(regions, _VALIDITY_TR_LABELS, label_region=tr_label)

    # Avoid letting a generic "VALIDITY" match collide with the TR row: if the
    # generic match resolved to the same region as the TR label, ignore it.
    primary = None
    if nt_label is not None:
        primary = _labelled_date(regions, _VALIDITY_NT_LABELS, label_region=nt_label)
    if primary is None and generic_label is not None and generic_label is not tr_label:
        primary = _labelled_date(regions, _VALIDITY_LABELS, label_region=generic_label)

    # If we only found a transport date, surface it as the primary too so the
    # field is never silently empty when a validity date plainly exists.
    if primary is None and transport is not None:
        primary = transport

    return primary, transport


# ---------------------------------------------------------------------------
# Name / relation
# ---------------------------------------------------------------------------

# Any region whose normalised text matches one of these is a field label, not a
# value — used to reject a label that was mistakenly picked up as a name/relation.
_ALL_LABEL_WORDS = frozenset(
    word
    for label_set in (
        _NAME_LABELS,
        _RELATION_LABELS,
        _DOB_LABELS,
        _DOI_LABELS,
        _VALIDITY_LABELS,
        _VALIDITY_NT_LABELS,
        _VALIDITY_TR_LABELS,
        _BLOOD_GROUP_LABELS,
        _COV_LABELS,
        _PRESENT_ADDRESS_LABELS,
        _PERMANENT_ADDRESS_LABELS,
        _GENERIC_ADDRESS_LABELS,
    )
    for word in label_set
)


def _is_known_label(text: str) -> bool:
    norm = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    return norm in _ALL_LABEL_WORDS


def _looks_like_value(text: str) -> bool:
    """True if a string looks like a usable name/value rather than empty noise."""
    cleaned = text.strip()
    return len(re.sub(r"[^A-Za-z]", "", cleaned)) >= 2


def _find_name(regions: list[TextRegion]) -> Optional[str]:
    """Resolve the holder name, avoiding the relation (S/D/W of) value.

    ``find_visual_field`` for "NAME" can latch onto a relation label whose
    text also contains "NAME" in bilingual cards; we explicitly prefer a label
    that is exactly/primarily a name label and is not a relation label.
    """
    value = find_label_value(regions, _NAME_LABELS)
    if value and _looks_like_value(value) and not _is_known_label(value):
        return value.strip()
    return None


def _find_relation(regions: list[TextRegion]) -> Optional[str]:
    value = find_label_value(regions, _RELATION_LABELS)
    if value and _looks_like_value(value) and not _is_known_label(value):
        return value.strip()
    return None


# ---------------------------------------------------------------------------
# Blood group / class of vehicle
# ---------------------------------------------------------------------------

def _normalise_blood_group(text: str) -> Optional[str]:
    upper = text.upper()
    # Never read a blood group out of the label words themselves.
    if re.search(r"BLOOD|GROUP|\bBG\b", upper):
        return None
    m = _BLOOD_GROUP_RE.search(upper)
    if not m:
        return None
    group = m.group(1)
    suffix = m.group(2)
    sign = "+" if suffix[0] in "+P" or suffix.upper().startswith("POS") else "-"
    return f"{group}{sign}"


def _find_blood_group(regions: list[TextRegion]) -> Optional[str]:
    label = find_visual_field(regions, _BLOOD_GROUP_LABELS)
    if label is not None:
        # Value may sit to the right, below, or (rarely) on the label region.
        for candidate_text in (
            getattr(find_visual_value_right(regions, label), "text", "") or "",
            getattr(find_visual_value_near(regions, label), "text", "") or "",
            label.text,
        ):
            bg = _normalise_blood_group(candidate_text)
            if bg:
                return bg
    return None


def _find_class_of_vehicle(regions: list[TextRegion]) -> Optional[str]:
    """Collect class-of-vehicle (COV) tokens (e.g. ``MCWG``, ``LMV``).

    Returns the COV value adjacent to a COV label; falls back to scanning for
    canonical COV tokens anywhere on the card (multiple classes joined).
    """
    label = find_visual_field(regions, _COV_LABELS)
    if label is not None:
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            tokens = _extract_cov_tokens(value.text)
            if tokens:
                return ", ".join(tokens)

    # Fallback: scan the whole card for canonical COV tokens.
    found: list[str] = []
    for region in regions:
        for tok in _extract_cov_tokens(region.text):
            if tok not in found:
                found.append(tok)
    return ", ".join(found) if found else None


def _extract_cov_tokens(text: str) -> list[str]:
    upper = re.sub(r"\s+", " ", text.upper())
    found: list[str] = []
    for tok in _COV_TOKENS:  # longest-first ordering in the list avoids LMV ⊂ LMV-NT
        if re.search(rf"(?<![A-Z0-9-]){re.escape(tok)}(?![A-Z0-9])", upper):
            if not any(tok in existing for existing in found):
                found.append(tok)
    return found


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

def _collect_address_block(
    regions: list[TextRegion], label: TextRegion
) -> Optional[str]:
    """Collect the (possibly multi-line) address block beneath/right of a label."""
    label_bottom = max(p[1] for p in label.bbox)
    label_top = min(p[1] for p in label.bbox)
    label_left = min(p[0] for p in label.bbox)

    lines: list[tuple[int, int, str]] = []

    # Inline value on the same row as the label (e.g. "Address : 14 Nehru Nagar").
    inline = find_visual_value_right(regions, label)
    if inline is not None and not _is_other_label(inline.text):
        lines.append((label_top, min(p[0] for p in inline.bbox), inline.text.strip()))

    # Candidate rows below the label, left-aligned with the label column.
    candidates: list[tuple[int, int, str]] = []
    for region in regions:
        if region is label or region is inline:
            continue
        top = min(p[1] for p in region.bbox)
        left = min(p[0] for p in region.bbox)
        # Must start below the label and within a reasonable block height.
        if top <= label_bottom - 5 or top - label_bottom > 220:
            continue
        # Roughly left-aligned with the label column.
        if abs(left - label_left) > 320:
            continue
        text = region.text.strip()
        if len(text) < 2:
            continue
        candidates.append((top, left, text))

    # Walk the rows top-to-bottom and stop at the first row that begins a
    # *different* field (its label), so the next field's value cannot leak in.
    candidates.sort(key=lambda x: (x[0], x[1]))
    stop_y: Optional[int] = None
    for top, _left, text in candidates:
        if _is_other_label(text):
            stop_y = top
            break
    for top, left, text in candidates:
        if stop_y is not None and top >= stop_y:
            continue
        lines.append((top, left, text))

    if not lines:
        return None

    lines.sort(key=lambda x: (x[0], x[1]))
    seen: set[str] = set()
    ordered: list[str] = []
    for _, _, text in lines:
        if text not in seen:
            seen.add(text)
            ordered.append(text)
    return ", ".join(ordered[:6])


_OTHER_LABEL_HINTS = [
    "DL NO",
    "LICENCE NO",
    "LICENSE NO",
    "NAME",
    "DATE OF BIRTH",
    "DOB",
    "DATE OF ISSUE",
    "VALID",
    "VALIDITY",
    "BLOOD GROUP",
    "CLASS OF VEHICLE",
    "COV",
    "SIGNATURE",
    "ISSUING AUTHORITY",
    "AUTHORITY",
]


def _is_other_label(text: str) -> bool:
    """True if a region reads like a *different* field label (stop the block)."""
    upper = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    padded = f" {upper} "
    return any(f" {hint} " in padded for hint in _OTHER_LABEL_HINTS)


def _find_address(regions: list[TextRegion]) -> Optional[str]:
    """Collect the address block, preferring the present/current address.

    Order of preference:
      1. Present / Current / Temporary address.
      2. Permanent address.
      3. Generic "Address" label.
    """
    for label_set in (
        _PRESENT_ADDRESS_LABELS,
        _PERMANENT_ADDRESS_LABELS,
        _GENERIC_ADDRESS_LABELS,
    ):
        label = find_visual_field(regions, label_set)
        if label is None:
            continue
        block = _collect_address_block(regions, label)
        if block:
            return block
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_driving_licence(regions: list[TextRegion]) -> DrivingLicenceFields:
    fields = DrivingLicenceFields()
    fields.dl_number = _find_dl_number(regions)
    fields.name = _find_name(regions)
    fields.relation_name = _find_relation(regions)
    fields.date_of_birth = _labelled_date(regions, _DOB_LABELS)
    fields.issue_date = _labelled_date(regions, _DOI_LABELS)
    primary_validity, transport_validity = _find_validity_date(regions)
    fields.validity_date = primary_validity
    fields.validity_date_transport = transport_validity
    fields.blood_group = _find_blood_group(regions)
    fields.class_of_vehicle = _find_class_of_vehicle(regions)
    fields.address = _find_address(regions)
    return fields
