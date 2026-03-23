"""
Cross-validates MRZ output against visual OCR fields and computes
a final confidence score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from rapidfuzz import fuzz

from .mrz_parser import MRZResult
from .ocr_engine import TextRegion

# ---------------------------------------------------------------------------
# ISO 3166-1 alpha-3 country codes (subset — full list is ~249)
# ---------------------------------------------------------------------------

# fmt: off
_VALID_COUNTRY_CODES = {
    "AFG", "ALB", "DZA", "AND", "AGO", "ATG", "ARG", "ARM", "AUS", "AUT",
    "AZE", "BHS", "BHR", "BGD", "BRB", "BLR", "BEL", "BLZ", "BEN", "BTN",
    "BOL", "BIH", "BWA", "BRA", "BRN", "BGR", "BFA", "BDI", "KHM", "CMR",
    "CAN", "CPV", "CAF", "TCD", "CHL", "CHN", "COL", "COM", "COG", "COD",
    "CRI", "CIV", "HRV", "CUB", "CYP", "CZE", "DNK", "DJI", "DMA", "DOM",
    "ECU", "EGY", "SLV", "GNQ", "ERI", "EST", "SWZ", "ETH", "FJI", "FIN",
    "FRA", "GAB", "GMB", "GEO", "DEU", "GHA", "GRC", "GRD", "GTM", "GIN",
    "GNB", "GUY", "HTI", "HND", "HUN", "ISL", "IND", "IDN", "IRN", "IRQ",
    "IRL", "ISR", "ITA", "JAM", "JPN", "JOR", "KAZ", "KEN", "KIR", "PRK",
    "KOR", "KWT", "KGZ", "LAO", "LVA", "LBN", "LSO", "LBR", "LBY", "LIE",
    "LTU", "LUX", "MDG", "MWI", "MYS", "MDV", "MLI", "MLT", "MHL", "MRT",
    "MUS", "MEX", "FSM", "MDA", "MCO", "MNG", "MNE", "MAR", "MOZ", "MMR",
    "NAM", "NRU", "NPL", "NLD", "NZL", "NIC", "NER", "NGA", "MKD", "NOR",
    "OMN", "PAK", "PLW", "PAN", "PNG", "PRY", "PER", "PHL", "POL", "PRT",
    "QAT", "ROU", "RUS", "RWA", "KNA", "LCA", "VCT", "WSM", "SMR", "STP",
    "SAU", "SEN", "SRB", "SYC", "SLE", "SGP", "SVK", "SVN", "SLB", "SOM",
    "ZAF", "SSD", "ESP", "LKA", "SDN", "SUR", "SWE", "CHE", "SYR", "TWN",
    "TJK", "TZA", "THA", "TLS", "TGO", "TON", "TTO", "TUN", "TUR", "TKM",
    "TUV", "UGA", "UKR", "ARE", "GBR", "USA", "URY", "UZB", "VUT", "VEN",
    "VNM", "YEM", "ZMB", "ZWE",
    # Common MRZ-specific codes
    "D<<",  # Germany uses "D<<" in some contexts
    "GBD", "GBN", "GBO", "GBP", "GBS",  # British territories
    "XBA", "XIM", "XCC", "XOM", "XXA", "XXB", "XXC",  # special codes
    "UNO", "UNA",  # UN
    "EUE",  # EU
}
# fmt: on


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
    """Find a visual OCR region whose text contains one of the given keywords."""
    for region in regions:
        text_upper = region.text.upper()
        for kw in keywords:
            if kw.upper() in text_upper:
                return region
    return None


def find_visual_value_near(
    regions: list[TextRegion],
    label_region: TextRegion,
    max_y_distance: int = 80,
) -> Optional[TextRegion]:
    """Find the OCR region immediately below a label region."""
    label_bottom = max(p[1] for p in label_region.bbox)
    label_left = min(p[0] for p in label_region.bbox)

    candidates = []
    for region in regions:
        top = min(p[1] for p in region.bbox)
        left = min(p[0] for p in region.bbox)
        if top > label_bottom and (top - label_bottom) < max_y_distance:
            x_distance = abs(left - label_left)
            if x_distance < 200:
                candidates.append((top - label_bottom + x_distance * 0.3, region))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


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
        name_label = find_visual_field(regions, ["SURNAME", "NAME", "NOM"])
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
        dob_label = find_visual_field(regions, ["DATE OF BIRTH", "DOB", "BIRTH", "NAISSANCE"])
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
        exp_label = find_visual_field(regions, ["EXPIRY", "EXPIRATION", "DATE OF EXPIRY", "VALID"])
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
        if mrz.country_code.value:
            code = mrz.country_code.value.upper()
            if code not in _VALID_COUNTRY_CODES:
                warnings.append(f"UNKNOWN_COUNTRY_CODE_{code}")

        # Date sanity checks
        if mrz.date_of_birth.value and mrz.expiry_date.value:
            try:
                dob = date.fromisoformat(mrz.date_of_birth.value)
                exp = date.fromisoformat(mrz.expiry_date.value)
                if exp <= dob:
                    errors.append("EXPIRY_BEFORE_DOB")
            except ValueError:
                pass

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
