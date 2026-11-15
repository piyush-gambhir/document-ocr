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


    stop_keywords: set[str] = set()
    if stop_labels:
        for label_group in stop_labels:
            for kw in label_group:
                stop_keywords.add(kw.upper())

    def _is_stop_label(text: str) -> bool:
        norm = re.sub(r"[^A-Z0-9 ]", "", text.upper()).strip()
        return any(kw in norm for kw in stop_keywords)



    row_for_top: dict[int, list[TextRegion]] = {}
    for region in regions:
        if region is label_region:
            continue
        top = min(p[1] for p in region.bbox)
        if top < label_bottom - 10:
            continue
        if top - label_bottom > 300:
            continue

        bucket = top // 12
        row_for_top.setdefault(bucket, []).append(region)

    sorted_rows = sorted(row_for_top.items())

    collected: list[TextRegion] = []
    prev_bottom = label_bottom
    for _, row_regions in sorted_rows:
        if len(collected) >= max_lines:
            break

        if any(_is_stop_label(r.text) for r in row_regions):
            break

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






def _parse_address(address_regions: list[TextRegion]) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Parse address regions into (full_address, pincode, city, state)."""
    lines = [r.text.strip() for r in address_regions if r.text.strip()]
    full_address = ", ".join(lines)


    pincode_match = re.search(r"\b(\d{6})\b", full_address)
    pincode = pincode_match.group(1) if pincode_match else None




    state, city = _scan_state_and_city_from_tokens(full_address)



    if state is None or city is None:
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()


            m = re.match(r"^([A-Za-z\s.]+?)[\s-]+\d{6}\s+([A-Z]{2,3})$", line)
            if m and m.group(2).upper() in _STATE_CODES:
                city = city or m.group(1).strip()
                state = state or _STATE_CODES[m.group(2).upper()]
                continue


            m = re.match(r"^([A-Za-z\s.]+?)\s+(\d{6})\s+([A-Z]{2,3})$", line)
            if m and m.group(3).upper() in _STATE_CODES:
                city = city or m.group(1).strip()
                state = state or _STATE_CODES[m.group(3).upper()]
                continue


            if line.upper() in _STATE_NAMES_UPPER:
                state = state or line.strip()
                if i > 0 and not city:
                    city = lines[i - 1].strip()
                continue


            m = re.match(r"^([A-Za-z\s]+?)[\s-]*\d{6}$", line)
            if m and m.group(1).strip().upper() in _STATE_NAMES_UPPER:
                state = state or m.group(1).strip()
                if i > 0 and not city:
                    city = lines[i - 1].strip()
                continue


            m = re.match(r"^([A-Za-z\s.]+?)[\s-]+\d{6}$", line)
            if m and not city:
                city = m.group(1).strip()
                continue




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

        tok = re.sub(r"^PIN[\s:]*", "", tok, flags=re.IGNORECASE).strip()
        if not tok or re.fullmatch(r"\d{4,6}", tok):
            continue
        tokens.append(tok)



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






def extract_back_page(regions: list[TextRegion]) -> BackPageFields:
    """Extract structured fields from a passport back page using spatial layout.

    Uses label→value-below relationships via bounding boxes. This approach
    is format-agnostic and works across old and new Indian passport generations
    because the field labels are consistent even though the visual layout varies.
    """
    fields = BackPageFields()


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


    address_label = find_visual_field(regions, _ADDRESS_LABELS)
    if address_label:

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







    old_pp_label = find_visual_field(regions, _OLD_PASSPORT_LABELS)
    if old_pp_label:
        pp_no, doi, poi = _extract_old_passport_row(regions, old_pp_label)
        fields.old_passport_number = pp_no
        fields.old_passport_date_of_issue = doi
        fields.old_passport_place_of_issue = poi




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


        if pp_no is None and _PASSPORT_NUMBER_RE.fullmatch(upper):
            pp_no = upper
            continue
        if doi is None and _DATE_RE.match(text):
            doi = text
            continue
        if poi is None and not any(ch.isdigit() for ch in text):
            poi = text

    return pp_no, doi, poi
