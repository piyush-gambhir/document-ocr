"""
Cross-validates MRZ output against visual OCR fields and computes
a final confidence score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from rapidfuzz import fuzz

from .mrz_parser import MRZResult
from .ocr_engine import TextRegion

# Shared ISO/ICAO code validation also covers travel-card and visa recovery.
from .document_registry import is_known_mrz_country

_LABEL_HINTS = [
    "SURNAME",
    "GIVEN NAME",
    "NAME",
    "DATE",
    "BIRTH",
    "NATIONALITY",
    "PASSPORT",
    "SEX",
    "PLACE",
    "ISSUE",
    "EXPIRY",
    "EXPIRATION",
    "VALID",
    "COUNTRY",
    "CODE",
    "FATHER",
    "MOTHER",
    "SPOUSE",
    "ADDRESS",
    "FILE",
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    confidence: float  # 0.0 – 1.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_visual_field(
    regions: list[TextRegion],
    keywords: list[str],
) -> Optional[TextRegion]:
    """Find the best label match for the given keywords.

    OCR label text is noisy, so prefer exact phrase matches and longer, more
    specific keywords over generic substring matches.
    """
    normalised_keywords = [_normalise_label_text(keyword) for keyword in keywords]
    best_match: tuple[int, float, TextRegion] | None = None

    for region in regions:
        label_text = _normalise_label_text(region.text)
        if not label_text:
            continue

        for priority, keyword in enumerate(normalised_keywords):
            if not keyword:
                continue

            padded_label = f" {label_text} "
            padded_keyword = f" {keyword} "

            if label_text == keyword:
                score = 10_000 - priority
            elif label_text.startswith(keyword + " "):
                # An inline "Name: value" is stronger than NAME occurring
                # inside "Father's Name: value", regardless of OCR confidence.
                score = 2_000 + (len(keyword) * 100) - priority
            elif padded_keyword in padded_label:
                score = (len(keyword) * 100) - priority
            else:
                continue

            if best_match is None or score > best_match[0] or (
                score == best_match[0] and region.confidence > best_match[1]
            ):
                best_match = (score, region.confidence, region)

    return best_match[2] if best_match else None


def find_label_row_left_edge(
    regions: list[TextRegion],
    label_region: TextRegion,
    *,
    max_prefix_chars: int = 5,
) -> int:
    """Leftmost x of the label *row*, absorbing short bilingual-prefix regions.

    Bilingual passports (Hindi/English, Arabic/English, Cyrillic/English, …)
    produce labels OCR'd as multiple regions on the same row, e.g.
    `"पिता / "` (often mis-OCR'd as "fe /") followed by
    `"Name of Father / Legal Guardian"`. Form values align to the leftmost
    edge of the bilingual block, not to the English region alone.

    Only short fragments (≤ `max_prefix_chars` alphanumeric characters) are
    absorbed — long same-row regions are usually values from adjacent fields
    in multi-column layouts (e.g. the Place-of-Issue value sitting on the same
    row as the Date-of-Issue label on the biodata page) and must NOT shift
    the label's effective left edge.
    """
    label_top = min(p[1] for p in label_region.bbox)
    label_bottom = max(p[1] for p in label_region.bbox)
    label_height = max(label_bottom - label_top, 1)
    leftmost = min(p[0] for p in label_region.bbox)

    for region in regions:
        if region is label_region:
            continue
        top = min(p[1] for p in region.bbox)
        bottom = max(p[1] for p in region.bbox)
        overlap = min(bottom, label_bottom) - max(top, label_top)
        if overlap < label_height * 0.5:
            continue
        left = min(p[0] for p in region.bbox)
        if left >= leftmost:
            continue
        alnum_len = len(re.sub(r"[^A-Za-z0-9]", "", region.text))
        if alnum_len > max_prefix_chars:
            continue
        leftmost = left

    return leftmost


def find_visual_value_near(
    regions: list[TextRegion],
    label_region: TextRegion,
    max_y_distance: int = 80,
) -> Optional[TextRegion]:
    """Find the OCR region immediately below a label region."""
    label_bottom = max(p[1] for p in label_region.bbox)
    label_left = find_label_row_left_edge(regions, label_region)
    min_vertical_overlap = 10

    candidates = []
    for region in regions:
        if region is label_region or _looks_like_field_label(region.text):
            continue
        top = min(p[1] for p in region.bbox)
        left = min(p[0] for p in region.bbox)
        vertical_gap = top - label_bottom
        if -min_vertical_overlap <= vertical_gap < max_y_distance:
            x_distance = abs(left - label_left)
            if x_distance < 200:
                candidates.append((max(vertical_gap, 0) + x_distance * 0.3, region))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def find_visual_value_right(
    regions: list[TextRegion],
    label_region: TextRegion,
    max_x_distance: int = 450,
) -> Optional[TextRegion]:
    """Find the value region on the same row, immediately to the right of a label.

    KYC cards (PAN / Aadhaar / DL / Voter ID) commonly lay fields out as
    "Label : value" on one line, unlike the passport's label-above-value form.
    """
    label_right = max(p[0] for p in label_region.bbox)
    label_top = min(p[1] for p in label_region.bbox)
    label_bottom = max(p[1] for p in label_region.bbox)
    label_height = max(label_bottom - label_top, 1)

    candidates = []
    for region in regions:
        if region is label_region:
            continue
        top = min(p[1] for p in region.bbox)
        bottom = max(p[1] for p in region.bbox)
        overlap = min(bottom, label_bottom) - max(top, label_top)
        if overlap < label_height * 0.4:
            continue
        left = min(p[0] for p in region.bbox)
        gap = left - label_right
        if 0 <= gap < max_x_distance:
            if _looks_like_field_label(region.text):
                continue
            candidates.append((gap, region))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


def find_label_value(
    regions: list[TextRegion],
    labels: list[str],
) -> Optional[str]:
    """Resolve an explicit inline value, then same-row-right and below."""
    label_region = find_visual_field(regions, labels)
    if label_region is None:
        return None
    # Detection can merge an entire printed "Label: value" row. Match the
    # label at the beginning, not an embedded word such as Name in Father's
    # Name. Preserve punctuation and casing in the actual printed value.
    tokens = list(re.finditer(r"[A-Za-z0-9]+", label_region.text))
    for label in sorted(labels, key=len, reverse=True):
        words = _normalise_label_text(label).split()
        if words and [t.group().upper() for t in tokens[:len(words)]] == words:
            inline = label_region.text[tokens[len(words) - 1].end():].strip(" :\t#")
            if inline and not _looks_like_field_label(inline):
                return inline
            break  # A longer empty label must not become a shorter label's value.
    value = find_visual_value_right(regions, label_region) or find_visual_value_near(
        regions, label_region
    )
    if value is None:
        return None
    text = value.text.strip()
    return text or None


def _parse_date_flexible(text: str) -> Optional[date]:
    """Try multiple date formats to parse a visual date field."""
    text = text.strip().replace("/", "-").replace(".", "-")
    formats = ["%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%Y%m%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalise_label_text(text: str) -> str:
    """Normalise OCR label text so phrase matching is less brittle."""
    text = text.upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_field_label(text: str) -> bool:
    """Heuristic to avoid treating the next label as a field value."""
    normalised = _normalise_label_text(text)
    padded = f" {normalised} "
    return any(f" {hint} " in padded for hint in _LABEL_HINTS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(
    mrz: Optional[MRZResult],
    regions: list[TextRegion],
) -> ValidationResult:
    """
    Cross-validate MRZ fields against visual OCR regions and compute
    a final confidence score.

    Confidence = weighted average of:
      - MRZ checksum validity: 40%
      - Field cross-match: 30%
      - Individual field OCR confidence: 30%
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- MRZ checksum component (40%) ---
    if mrz is None:
        mrz_score = 0.0
        errors.append("MRZ_NOT_DETECTED")
    elif mrz.overall_checksum_valid:
        mrz_score = 1.0
    else:
        # Partial credit: count how many individual fields pass
        checks = [
            mrz.passport_number.checksum_valid,
            mrz.date_of_birth.checksum_valid,
            mrz.expiry_date.checksum_valid,
        ]
        passed = sum(1 for c in checks if c)
        mrz_score = passed / len(checks) * 0.7  # cap at 0.7 if overall fails

    # --- Cross-match component (30%) ---
    cross_matches = 0
    cross_total = 0

    if mrz is not None:
        # Name cross-match
        name_label = find_visual_field(regions, ["SURNAME", "FAMILY NAME", "LAST NAME", "NOM"])
        if name_label:
            name_value = find_visual_value_near(regions, name_label)
            if name_value and mrz.surname.value:
                cross_total += 1
                ratio = fuzz.token_sort_ratio(
                    mrz.surname.value.upper(),
                    name_value.text.upper(),
                )
                if ratio >= 85:
                    cross_matches += 1
                elif ratio >= 60:
                    cross_matches += 0.5
                    warnings.append("NAME_PARTIAL_MATCH")
                else:
                    warnings.append("NAME_MISMATCH")

        # DOB cross-match
        dob_label = find_visual_field(regions, ["DATE OF BIRTH", "BIRTH DATE", "DOB", "NAISSANCE"])
        if dob_label and mrz.date_of_birth.value:
            dob_value = find_visual_value_near(regions, dob_label)
            if dob_value:
                cross_total += 1
                visual_date = _parse_date_flexible(dob_value.text)
                if visual_date and str(visual_date) == mrz.date_of_birth.value:
                    cross_matches += 1
                else:
                    warnings.append("DOB_MISMATCH")

        # Expiry cross-match
        exp_label = find_visual_field(
            regions,
            ["DATE OF EXPIRY", "EXPIRY DATE", "DATE OF EXPIRATION", "EXPIRY", "EXPIRATION", "VALID UNTIL"],
        )
        if exp_label and mrz.expiry_date.value:
            exp_value = find_visual_value_near(regions, exp_label)
            if exp_value:
                cross_total += 1
                visual_date = _parse_date_flexible(exp_value.text)
                if visual_date and str(visual_date) == mrz.expiry_date.value:
                    cross_matches += 1
                else:
                    warnings.append("EXPIRY_DATE_MISMATCH")

        # Country code validation
        code = (mrz.country_code.value or "").upper()
        if not is_known_mrz_country(code):
            reason = f"UNKNOWN_COUNTRY_CODE_{code}" if code else "MISSING_COUNTRY_CODE"
            warnings.append(reason)
            errors.append(reason)
        if not is_known_mrz_country(mrz.nationality.value):
            errors.append("UNKNOWN_NATIONALITY")

        # A correct checksum does not establish that a date exists. Unknown
        # date components are permitted as fillers, but impossible numeric
        # dates must not disappear silently when the parser returns None.
        parsed_dates: dict[str, date] = {}
        for name, field in (("DATE_OF_BIRTH", mrz.date_of_birth), ("EXPIRY_DATE", mrz.expiry_date)):
            if field.value is None:
                if re.fullmatch(r"[0-9<]{6}", field.raw) and "<" in field.raw:
                    warnings.append(f"INCOMPLETE_{name}")
                else:
                    errors.append(f"INVALID_{name}")
                continue
            try:
                parsed_dates[name] = date.fromisoformat(field.value)
            except ValueError:
                errors.append(f"INVALID_{name}")
        if len(parsed_dates) == 2 and parsed_dates["EXPIRY_DATE"] <= parsed_dates["DATE_OF_BIRTH"]:
            errors.append("EXPIRY_BEFORE_DOB")

    cross_score = (cross_matches / cross_total) if cross_total > 0 else 0.5

    # --- OCR confidence component (30%) ---
    if regions:
        avg_conf = sum(r.confidence for r in regions) / len(regions)
    else:
        avg_conf = 0.0

    # --- Weighted average ---
    confidence = (mrz_score * 0.40) + (cross_score * 0.30) + (avg_conf * 0.30)
    confidence = round(min(max(confidence, 0.0), 1.0), 3)

    return ValidationResult(
        confidence=confidence,
        errors=errors,
        warnings=warnings,
    )
