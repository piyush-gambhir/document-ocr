"""
Spatial extraction of Indian passport back page fields.

Uses label→value-below-label relationships via bounding boxes,
making it format-agnostic across old and new passport generations.

Indian passport back page fields (consistent across all generations):
  - Name of Father / Legal Guardian
  - Name of Mother
  - Name of Spouse
  - Address
  - File Number
  - Old Passport Number / Date of Issue / Place of Issue (renewals only)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ocr_engine import TextRegion
from .validator import find_label_row_left_edge, find_visual_field, find_visual_value_near


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class BackPageFields:
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    spouse_name: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    file_number: Optional[str] = None
    old_passport_number: Optional[str] = None
    old_passport_date_of_issue: Optional[str] = None
    old_passport_place_of_issue: Optional[str] = None


# ---------------------------------------------------------------------------
# Indian state codes for address parsing
# ---------------------------------------------------------------------------

_STATE_CODES: dict[str, str] = {
    "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
    "BR": "Bihar", "CG": "Chhattisgarh", "GA": "Goa", "GJ": "Gujarat",
    "HR": "Haryana", "HP": "Himachal Pradesh", "JH": "Jharkhand",
    "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh",
    "MH": "Maharashtra", "MN": "Manipur", "ML": "Meghalaya",
    "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha", "OR": "Odisha",
    "PB": "Punjab", "RJ": "Rajasthan", "SK": "Sikkim", "TN": "Tamil Nadu",
    "TS": "Telangana", "TR": "Tripura", "UP": "Uttar Pradesh",
    "UK": "Uttarakhand", "WB": "West Bengal",
    "AN": "Andaman and Nicobar Islands", "CH": "Chandigarh",
    "DN": "Dadra and Nagar Haveli and Daman and Diu",
    "DD": "Dadra and Nagar Haveli and Daman and Diu",
    "DL": "Delhi", "JK": "Jammu and Kashmir", "LA": "Ladakh",
    "LD": "Lakshadweep", "PY": "Puducherry",
}

_STATE_NAMES_UPPER = {name.upper() for name in _STATE_CODES.values()}
_UPPER_TO_CANONICAL_STATE = {name.upper(): name for name in _STATE_CODES.values()}


# ---------------------------------------------------------------------------
# Label keywords (English + common OCR misreads)
# Bilingual Hindi/English labels appear on all Indian passport formats.
# OCR mostly reads the English portion; Hindi text is noise-filtered by
# the label matcher.
# ---------------------------------------------------------------------------

_FATHER_LABELS = [
    "NAME OF FATHER", "FATHER LEGAL GUARDIAN", "NAME OF FATHER LEGAL GUARDIAN",
    "FATHER", "LEGAL GUARDIAN",
]

_MOTHER_LABELS = [
    "NAME OF MOTHER", "MOTHER",
]

_SPOUSE_LABELS = [
    "NAME OF SPOUSE", "SPOUSE",
]

_ADDRESS_LABELS = [
    "ADDRESS",
]

_FILE_NO_LABELS = [
    "FILE NO", "FILE NUMBER", "FILE NO.",
]

_OLD_PASSPORT_LABELS = [
    "OLD PASSPORT NO", "OLD PASSPORT NUMBER", "PREVIOUS PASSPORT",
    "OLD PASSPORT NO.", "OLD PASSPORT",
]

_OLD_PASSPORT_DOI_LABELS = [
    "DATE OF ISSUE",
]

_OLD_PASSPORT_POI_LABELS = [
    "PLACE OF ISSUE",
]


# ---------------------------------------------------------------------------
# Multi-line collection
# ---------------------------------------------------------------------------

def _collect_multiline_value(
    regions: list[TextRegion],
    label_region: TextRegion,
    *,
    max_lines: int = 5,
    max_y_gap: int = 50,
    stop_labels: Optional[list[list[str]]] = None,
) -> list[TextRegion]:
    """Collect multiple value regions below a label (for address blocks).

    Keeps collecting lines below the label until we hit a stop label
    (anywhere on a row, regardless of horizontal alignment), exceed
    max_lines, or the vertical gap is too large.
    """
    label_bottom = max(p[1] for p in label_region.bbox)
    label_left = find_label_row_left_edge(regions, label_region)

    # All stop-label keywords
    stop_keywords: set[str] = set()
    if stop_labels:
        for label_group in stop_labels:
            for kw in label_group:
                stop_keywords.add(kw.upper())

    def _is_stop_label(text: str) -> bool:
        norm = re.sub(r"[^A-Z0-9 ]", "", text.upper()).strip()
        return any(kw in norm for kw in stop_keywords)

    # Group regions by row so we can stop on a row that contains a stop label
    # *anywhere* (including columns far from the address column).
    row_for_top: dict[int, list[TextRegion]] = {}
    for region in regions:
        if region is label_region:
            continue
        top = min(p[1] for p in region.bbox)
        if top < label_bottom - 10:
            continue
        if top - label_bottom > 300:
            continue
        # bucket by ~half-line height (assume ≥ 12 px lines)
        bucket = top // 12
        row_for_top.setdefault(bucket, []).append(region)

    sorted_rows = sorted(row_for_top.items())

    collected: list[TextRegion] = []
    prev_bottom = label_bottom
    for _, row_regions in sorted_rows:
        if len(collected) >= max_lines:
            break
        # Stop if any region in this row matches a stop label.
        if any(_is_stop_label(r.text) for r in row_regions):
            break
        # Pick the value-aligned region(s) — same column as the label.
        for region in row_regions:
            left = min(p[0] for p in region.bbox)
            if abs(left - label_left) >= 250:
                continue
            top = min(p[1] for p in region.bbox)
            if top - prev_bottom > max_y_gap and collected:
                break
            text = region.text.strip()
            if len(text) < 2:
                continue
            # Drop rows that are mostly non-Latin script (Hindi labels) — the
            # address proper is in Latin script even when adjacent labels are
            # bilingual.
            if _is_mostly_non_latin(text):
                continue
            collected.append(region)
            prev_bottom = max(p[1] for p in region.bbox)
            if len(collected) >= max_lines:
                break

    return collected


def _is_mostly_non_latin(text: str) -> bool:
    """True if more than half the alphabetic characters are non-ASCII."""
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return False
    non_latin = sum(1 for c in alpha if ord(c) > 127)
    return non_latin / len(alpha) > 0.5


# ---------------------------------------------------------------------------
# Address parsing
# ---------------------------------------------------------------------------

def _parse_address(address_regions: list[TextRegion]) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Parse address regions into (full_address, pincode, city, state)."""
    lines = [r.text.strip() for r in address_regions if r.text.strip()]
    full_address = ", ".join(lines)

    # Extract 6-digit pincode from anywhere in the address
    pincode_match = re.search(r"\b(\d{6})\b", full_address)
    pincode = pincode_match.group(1) if pincode_match else None

    # First pass: comma-tokenized scan. Handles addresses where the state
    # appears as its own token among other comma-separated tokens — e.g.
    # "NEW MAHAVIR NAGAR,DELHI" or "PIN:110018,DELHI,INDIA".
    state, city = _scan_state_and_city_from_tokens(full_address)

    # Second pass (fallback): per-line regex patterns. These handle line-
    # oriented formats where the state info is at the END of a single line.
    if state is None or city is None:
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()

            # Pattern: "CITY - PINCODE STATE_ABBREV"
            m = re.match(r"^([A-Za-z\s.]+?)[\s-]+\d{6}\s+([A-Z]{2,3})$", line)
            if m and m.group(2).upper() in _STATE_CODES:
                city = city or m.group(1).strip()
                state = state or _STATE_CODES[m.group(2).upper()]
                continue

            # Pattern: "CITY PINCODE STATE_ABBREV"
            m = re.match(r"^([A-Za-z\s.]+?)\s+(\d{6})\s+([A-Z]{2,3})$", line)
            if m and m.group(3).upper() in _STATE_CODES:
                city = city or m.group(1).strip()
                state = state or _STATE_CODES[m.group(3).upper()]
                continue

            # Pattern: standalone full state name
            if line.upper() in _STATE_NAMES_UPPER:
                state = state or line.strip()
                if i > 0 and not city:
                    city = lines[i - 1].strip()
                continue

            # Pattern: "STATE_FULLNAME - PINCODE" or "STATE_FULLNAME PINCODE"
            m = re.match(r"^([A-Za-z\s]+?)[\s-]*\d{6}$", line)
            if m and m.group(1).strip().upper() in _STATE_NAMES_UPPER:
                state = state or m.group(1).strip()
                if i > 0 and not city:
                    city = lines[i - 1].strip()
                continue

            # Pattern: "CITY - PINCODE" (state on a different line)
            m = re.match(r"^([A-Za-z\s.]+?)[\s-]+\d{6}$", line)
            if m and not city:
                city = m.group(1).strip()
                continue

    # Normalise the resolved state to canonical title case regardless of which
    # path set it (the per-line fallback patterns above capture the raw, often
    # all-caps, OCR text). Keeps output consistent — e.g. "KARNATAKA" → "Karnataka".
    if state and state.upper() in _UPPER_TO_CANONICAL_STATE:
        state = _UPPER_TO_CANONICAL_STATE[state.upper()]

    return full_address, pincode, city, state


def _scan_state_and_city_from_tokens(
    full_address: str,
) -> tuple[Optional[str], Optional[str]]:
    """Tokenize the full address by punctuation and infer state + city.

    The state is the first token that matches a known Indian state name or
    2-3 letter code. The city is the most recent preceding token that isn't
    a state, country, or pincode — so for "NEW MAHAVIR NAGAR,DELHI,INDIA"
    we get state=Delhi, city=NEW MAHAVIR NAGAR.
    """
    tokens: list[str] = []
    for raw in re.split(r"[,;|/]", full_address):
        tok = raw.strip()
        # Strip "PIN:" / "PIN " prefixes commonly stuck on the pincode token
        tok = re.sub(r"^PIN[\s:]*", "", tok, flags=re.IGNORECASE).strip()
        if not tok or re.fullmatch(r"\d{4,6}", tok):
            continue
        tokens.append(tok)

    # Map UPPER -> canonical title-case name so output is consistent
    # whether the OCR caught the full name or just the 2-letter code.
    upper_to_canonical = {name.upper(): name for name in _STATE_CODES.values()}

    state: Optional[str] = None
    state_idx = -1
    for i, tok in enumerate(tokens):
        upper = tok.upper()
        if upper in upper_to_canonical:
            state = upper_to_canonical[upper]
            state_idx = i
            break
        if upper in _STATE_CODES:
            state = _STATE_CODES[upper]
            state_idx = i
            break

    city: Optional[str] = None
    if state_idx > 0:
        for j in range(state_idx - 1, -1, -1):
            prev = tokens[j].strip()
            prev_upper = prev.upper()
            if prev_upper == "INDIA":
                continue
            if prev_upper in _STATE_NAMES_UPPER or prev_upper in _STATE_CODES:
                continue
            city = prev
            break

    return state, city


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_back_page(regions: list[TextRegion]) -> BackPageFields:
    """Extract structured fields from a passport back page using spatial layout.

    Uses label→value-below relationships via bounding boxes. This approach
    is format-agnostic and works across old and new Indian passport generations
    because the field labels are consistent even though the visual layout varies.
    """
    fields = BackPageFields()

    # --- Single-value fields (find label, get value below) ---
    father_label = find_visual_field(regions, _FATHER_LABELS)
    if father_label:
        val = find_visual_value_near(regions, father_label)
        if val:
            fields.father_name = val.text.strip()

    mother_label = find_visual_field(regions, _MOTHER_LABELS)
    if mother_label:
        val = find_visual_value_near(regions, mother_label)
        if val:
            fields.mother_name = val.text.strip()

    spouse_label = find_visual_field(regions, _SPOUSE_LABELS)
    if spouse_label:
        val = find_visual_value_near(regions, spouse_label)
        if val:
            fields.spouse_name = val.text.strip()

    file_label = find_visual_field(regions, _FILE_NO_LABELS)
    if file_label:
        val = find_visual_value_near(regions, file_label)
        if val:
            fields.file_number = val.text.strip()

    # --- Address (multi-line) ---
    address_label = find_visual_field(regions, _ADDRESS_LABELS)
    if address_label:
        # Collect lines below "Address" until we hit the next section
        address_regions = _collect_multiline_value(
            regions, address_label,
            max_lines=6,
            stop_labels=[_FILE_NO_LABELS, _OLD_PASSPORT_LABELS],
        )
        if address_regions:
            full_address, pincode, city, state = _parse_address(address_regions)
            fields.address = full_address
            fields.pincode = pincode
            fields.city = city
            fields.state = state

    # --- Old passport (renewals) ---
    # The Indian passport has a single compound label "Old Passport No. with
    # Date and Place of Issue" sitting above THREE columnar values:
    # passport_number | date_of_issue | place_of_issue. So instead of running
    # `find_visual_value_near` separately for each, we collect the whole row
    # below the label and assign by content shape.
    old_pp_label = find_visual_field(regions, _OLD_PASSPORT_LABELS)
    if old_pp_label:
        pp_no, doi, poi = _extract_old_passport_row(regions, old_pp_label)
        fields.old_passport_number = pp_no
        fields.old_passport_date_of_issue = doi
        fields.old_passport_place_of_issue = poi

        # Fall back to the separate-label path if we did not find the
        # passport number in the columnar row (e.g. layouts where the labels
        # are split into separate regions).
        if fields.old_passport_number is None:
            val = find_visual_value_near(regions, old_pp_label)
            if val:
                pp_match = re.search(r"[A-Z]\d{7}", val.text.upper())
                fields.old_passport_number = pp_match.group(0) if pp_match else val.text.strip()
        if fields.old_passport_date_of_issue is None:
            old_doi_label = find_visual_field(regions, _OLD_PASSPORT_DOI_LABELS)
            if old_doi_label and old_doi_label is not old_pp_label:
                old_pp_bottom = max(p[1] for p in old_pp_label.bbox)
                doi_top = min(p[1] for p in old_doi_label.bbox)
                if doi_top > old_pp_bottom - 30:
                    val = find_visual_value_near(regions, old_doi_label)
                    if val:
                        fields.old_passport_date_of_issue = val.text.strip()
        if fields.old_passport_place_of_issue is None:
            old_poi_label = find_visual_field(regions, _OLD_PASSPORT_POI_LABELS)
            if old_poi_label and old_poi_label is not old_pp_label:
                old_pp_bottom = max(p[1] for p in old_pp_label.bbox)
                poi_top = min(p[1] for p in old_poi_label.bbox)
                if poi_top > old_pp_bottom - 30:
                    val = find_visual_value_near(regions, old_poi_label)
                    if val:
                        fields.old_passport_place_of_issue = val.text.strip()

    return fields


# ---------------------------------------------------------------------------
# Old-passport row extraction (3 columns: passport_no | date | place_of_issue)
# ---------------------------------------------------------------------------

_PASSPORT_NUMBER_RE = re.compile(r"[A-Z]\d{7}")
_DATE_RE = re.compile(r"^\s*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\s*$")


_OLD_PASSPORT_ROW_LABEL_KEYWORDS = {"FILE", "ADDRESS", "FATHER", "MOTHER", "SPOUSE", "GUARDIAN"}


def _extract_old_passport_row(
    regions: list[TextRegion],
    old_pp_label: TextRegion,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Pull (passport_no, date_of_issue, place_of_issue) from the row directly
    below the compound Old-Passport label.

    The Indian passport back page (and several other formats) places these
    three fields in a single row under one wide label. Treating them as
    independent label/value pairs fails because there are no separate sub-
    labels — the three values must be classified by their content shape:
    a passport number, a date, and a place name.
    """
    label_top = min(p[1] for p in old_pp_label.bbox)
    label_bottom = max(p[1] for p in old_pp_label.bbox)
    label_center_y = (label_top + label_bottom) // 2

    # Use the label's vertical center as the lower bound, not the bottom —
    # OCR bboxes for labels are routinely taller than the visible glyphs, so
    # the value row often starts a few pixels above the label_bottom while
    # still being clearly the next form row.
    min_y = label_center_y
    max_y = label_bottom + 60

    row_regions: list[TextRegion] = []
    for region in regions:
        if region is old_pp_label:
            continue
        top = min(p[1] for p in region.bbox)
        if not (min_y <= top <= max_y):
            continue
        text = region.text.strip()
        if len(text) < 2 or _is_mostly_non_latin(text):
            continue
        # Skip neighbouring labels (File No., the next row's bilingual prefix, etc.)
        normalised_words = set(re.sub(r"[^A-Z]+", " ", text.upper()).split())
        if normalised_words & _OLD_PASSPORT_ROW_LABEL_KEYWORDS:
            continue
        row_regions.append(region)

    if not row_regions:
        return None, None, None

    row_regions.sort(key=lambda r: min(p[0] for p in r.bbox))

    pp_no: Optional[str] = None
    doi: Optional[str] = None
    poi: Optional[str] = None

    for region in row_regions:
        text = region.text.strip()
        upper = text.upper()
        # Passport number must MATCH the whole region exactly — otherwise we
        # would slice "L2072369" out of file-number text like "DL2072369058018".
        if pp_no is None and _PASSPORT_NUMBER_RE.fullmatch(upper):
            pp_no = upper
            continue
        if doi is None and _DATE_RE.match(text):
            doi = text
            continue
        if poi is None and not any(ch.isdigit() for ch in text):
            poi = text

    return pp_no, doi, poi
