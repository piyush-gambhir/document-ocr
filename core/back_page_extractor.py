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
from .validator import find_visual_field, find_visual_value_near


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

    Keeps collecting lines below the label until we hit another label,
    exceed max_lines, or the vertical gap is too large.
    """
    label_bottom = max(p[1] for p in label_region.bbox)
    label_left = min(p[0] for p in label_region.bbox)

    # All stop-label keywords
    stop_keywords: set[str] = set()
    if stop_labels:
        for label_group in stop_labels:
            for kw in label_group:
                stop_keywords.add(kw.upper())

    candidates: list[tuple[int, TextRegion]] = []
    for region in regions:
        if region is label_region:
            continue
        top = min(p[1] for p in region.bbox)
        left = min(p[0] for p in region.bbox)
        if top < label_bottom - 10:
            continue
        vertical_gap = top - label_bottom
        if vertical_gap > 300:
            continue
        x_distance = abs(left - label_left)
        if x_distance < 250:
            candidates.append((top, region))

    candidates.sort(key=lambda x: x[0])

    collected: list[TextRegion] = []
    prev_bottom = label_bottom
    for _, region in candidates:
        if len(collected) >= max_lines:
            break
        top = min(p[1] for p in region.bbox)
        if top - prev_bottom > max_y_gap and collected:
            break
        # Check if this line is a label (stop keyword)
        norm = re.sub(r"[^A-Z0-9 ]", "", region.text.upper()).strip()
        if any(kw in norm for kw in stop_keywords):
            break
        # Skip very short noise
        if len(region.text.strip()) < 2:
            continue
        collected.append(region)
        prev_bottom = max(p[1] for p in region.bbox)

    return collected


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

    city: Optional[str] = None
    state: Optional[str] = None

    # Scan lines bottom-up for state/city patterns
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()

        # Pattern: "CITY - PINCODE STATE_ABBREV"
        m = re.match(r"^([A-Za-z\s.]+?)[\s-]+\d{6}\s+([A-Z]{2,3})$", line)
        if m and m.group(2).upper() in _STATE_CODES:
            city = city or m.group(1).strip()
            state = state or m.group(2).strip()
            continue

        # Pattern: "CITY PINCODE STATE_ABBREV"
        m = re.match(r"^([A-Za-z\s.]+?)\s+(\d{6})\s+([A-Z]{2,3})$", line)
        if m and m.group(3).upper() in _STATE_CODES:
            city = city or m.group(1).strip()
            state = state or m.group(3).strip()
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

    return full_address, pincode, city, state


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
    old_pp_label = find_visual_field(regions, _OLD_PASSPORT_LABELS)
    if old_pp_label:
        val = find_visual_value_near(regions, old_pp_label)
        if val:
            # Passport numbers: letter followed by 7 digits
            pp_match = re.search(r"[A-Z]\d{7}", val.text.upper())
            fields.old_passport_number = pp_match.group(0) if pp_match else val.text.strip()

    old_doi_label = find_visual_field(regions, _OLD_PASSPORT_DOI_LABELS)
    # Only match "Date of Issue" that appears AFTER old passport section
    if old_doi_label and old_pp_label:
        old_pp_bottom = max(p[1] for p in old_pp_label.bbox)
        doi_top = min(p[1] for p in old_doi_label.bbox)
        if doi_top > old_pp_bottom - 30:
            val = find_visual_value_near(regions, old_doi_label)
            if val:
                fields.old_passport_date_of_issue = val.text.strip()

    old_poi_label = find_visual_field(regions, _OLD_PASSPORT_POI_LABELS)
    if old_poi_label and old_pp_label:
        old_pp_bottom = max(p[1] for p in old_pp_label.bbox)
        poi_top = min(p[1] for p in old_poi_label.bbox)
        if poi_top > old_pp_bottom - 30:
            val = find_visual_value_near(regions, old_poi_label)
            if val:
                fields.old_passport_place_of_issue = val.text.strip()

    return fields
