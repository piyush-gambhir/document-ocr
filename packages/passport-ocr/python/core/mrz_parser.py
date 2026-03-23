"""
MRZ (Machine Readable Zone) parser for TD3 passports (ICAO Doc 9303).

Parses the two 44-character MRZ lines, extracts fields by position,
and validates ICAO check digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .ocr_engine import TextRegion


# ---------------------------------------------------------------------------
# ICAO check digit
# ---------------------------------------------------------------------------

_WEIGHTS = [7, 3, 1]

_CHAR_VALUES = {str(i): i for i in range(10)}
_CHAR_VALUES.update({chr(c): c - 55 for c in range(65, 91)})  # A=10 .. Z=35
_CHAR_VALUES["<"] = 0

_DIGIT_CORRECTIONS = str.maketrans({
    "O": "0", "o": "0",
    "D": "0", "d": "0",
    "Q": "0", "q": "0",
    "I": "1", "i": "1",
    "l": "1", "L": "1",
    "Z": "2", "z": "2",
    "A": "4", "a": "4",
    "S": "5", "s": "5",
    "G": "6", "g": "6",
    "B": "8", "b": "8",
})


def _apply_digit_corrections(line2: str) -> str:
    """Apply digit corrections to known digit-only positions in MRZ line 2.
    Positions: [9] pn check, [13:19] DOB, [19] DOB check, [21:27] expiry,
    [27] expiry check, [42] personal check, [43] overall check.
    Does NOT touch [0:9] passport number, [10:13] nationality, [20] sex, [28:42] personal number."""
    chars = list(line2)
    digit_positions = [9, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 42, 43]
    for pos in digit_positions:
        if pos < len(chars):
            chars[pos] = chars[pos].translate(_DIGIT_CORRECTIONS)
    return "".join(chars)


def icao_check_digit(data: str) -> int:
    """Compute ICAO weighted checksum for a string of MRZ characters."""
    total = 0
    for i, ch in enumerate(data):
        val = _CHAR_VALUES.get(ch.upper(), 0)
        total += val * _WEIGHTS[i % 3]
    return total % 10


def verify_check_digit(data: str, expected: str) -> bool:
    """Verify a single check digit field."""
    try:
        return icao_check_digit(data) == int(expected)
    except (ValueError, IndexError):
        return False


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_mrz_date(yymmdd: str) -> Optional[str]:
    """Convert YYMMDD to ISO 8601 YYYY-MM-DD. YY >= 30 → 19YY, else 20YY."""
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    century = 1900 if yy >= 30 else 2000
    year = century + yy
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    return f"{year:04d}-{mm:02d}-{dd:02d}"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class MRZField:
    value: Optional[str]
    raw: str
    checksum_valid: Optional[bool] = None  # None if no checksum for this field


@dataclass
class MRZResult:
    """Parsed MRZ result with all fields and validation info."""
    document_type: MRZField
    country_code: MRZField
    surname: MRZField
    given_names: MRZField
    passport_number: MRZField
    nationality: MRZField
    date_of_birth: MRZField
    sex: MRZField
    expiry_date: MRZField
    personal_number: MRZField
    overall_checksum_valid: bool
    raw_lines: tuple[str, str]
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MRZ line detection
# ---------------------------------------------------------------------------

_MRZ_PATTERN = re.compile(r"^[A-Z0-9<]{40,44}$")


def _clean_mrz_text(raw: str) -> str:
    """Clean OCR text for MRZ matching — fix common substitution errors."""
    text = raw.upper().replace(" ", "")
    # Common OCR substitutions for the '<' filler character
    text = text.replace("«", "<").replace("‹", "<").replace(">", "<")
    return text


def _find_mrz_lines(regions: list[TextRegion]) -> Optional[tuple[str, str]]:
    """Identify the two MRZ lines from OCR output."""
    candidates: list[str] = []

    for region in regions:
        text = _clean_mrz_text(region.text)
        if _MRZ_PATTERN.match(text) and len(text) >= 40:
            candidates.append(text)

    if len(candidates) < 2:
        return None

    # Take the last two matching lines (MRZ is at the bottom)
    # Sort by vertical position (bottom of bounding box)
    mrz_regions = []
    for region in regions:
        text = _clean_mrz_text(region.text)
        if _MRZ_PATTERN.match(text) and len(text) >= 40:
            y_pos = max(p[1] for p in region.bbox) if region.bbox else 0
            mrz_regions.append((y_pos, text))

    mrz_regions.sort(key=lambda x: x[0])
    bottom_two = mrz_regions[-2:]

    line1 = _pad_to_44(bottom_two[0][1])
    line2 = _pad_to_44(bottom_two[1][1])

    return (line1, line2)


def _pad_to_44(line: str) -> str:
    """Pad MRZ line to 44 characters with '<' if shorter."""
    return line.ljust(44, "<")[:44]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _clean_name(raw: str) -> str:
    """Replace MRZ filler '<' with spaces and clean up."""
    return raw.replace("<", " ").strip()


def parse_mrz(regions: list[TextRegion]) -> Optional[MRZResult]:
    """
    Parse MRZ from OCR text regions.

    Returns None if MRZ lines cannot be identified.
    """
    lines = _find_mrz_lines(regions)
    if lines is None:
        return None

    line1, line2 = lines
    line2 = _apply_digit_corrections(line2)
    errors: list[str] = []

    # --- Line 1 ---
    # Pos 0:     document type (1 char, usually 'P')
    # Pos 1:     document type sub (1 char)
    # Pos 2-4:   issuing country (3 chars)
    # Pos 5-43:  name (surname << given names)

    doc_type_raw = line1[0:2]
    country_raw = line1[2:5]
    name_raw = line1[5:44]

    # Split name: surname and given names separated by "<<"
    name_parts = name_raw.split("<<", 1)
    surname_raw = name_parts[0] if name_parts else ""
    given_raw = name_parts[1] if len(name_parts) > 1 else ""

    # --- Line 2 ---
    # Pos 0-8:   passport number (9 chars)
    # Pos 9:     check digit for passport number
    # Pos 10-12: nationality (3 chars)
    # Pos 13-18: date of birth YYMMDD (6 chars)
    # Pos 19:    check digit for DOB
    # Pos 20:    sex (M/F/<)
    # Pos 21-26: expiry date YYMMDD (6 chars)
    # Pos 27:    check digit for expiry
    # Pos 28-41: personal number (14 chars)
    # Pos 42:    check digit for personal number
    # Pos 43:    overall check digit

    pn_raw = line2[0:9]
    pn_check = line2[9]
    nationality_raw = line2[10:13]
    dob_raw = line2[13:19]
    dob_check = line2[19]
    sex_raw = line2[20]
    expiry_raw = line2[21:27]
    expiry_check = line2[27]
    personal_raw = line2[28:42]
    personal_check = line2[42]
    overall_check = line2[43]

    # Validate check digits
    pn_valid = verify_check_digit(pn_raw, pn_check)
    dob_valid = verify_check_digit(dob_raw, dob_check)
    expiry_valid = verify_check_digit(expiry_raw, expiry_check)
    personal_valid = verify_check_digit(personal_raw, personal_check)

    # Overall check digit: computed over passport_number + check + DOB + check + expiry + check + personal + check
    composite = line2[0:10] + line2[13:20] + line2[21:43]
    overall_valid = verify_check_digit(composite, overall_check)

    if not pn_valid:
        errors.append("PASSPORT_NUMBER_CHECKSUM_FAILED")
    if not dob_valid:
        errors.append("DOB_CHECKSUM_FAILED")
    if not expiry_valid:
        errors.append("EXPIRY_CHECKSUM_FAILED")
    if not overall_valid:
        errors.append("OVERALL_CHECKSUM_FAILED")

    # Parse sex
    sex_value = None
    if sex_raw in ("M", "F"):
        sex_value = sex_raw
    elif sex_raw == "<" or sex_raw == "X":
        sex_value = "X"

    return MRZResult(
        document_type=MRZField(value=doc_type_raw.replace("<", "").strip() or "P", raw=doc_type_raw),
        country_code=MRZField(value=country_raw.replace("<", ""), raw=country_raw),
        surname=MRZField(value=_clean_name(surname_raw), raw=surname_raw),
        given_names=MRZField(value=_clean_name(given_raw), raw=given_raw),
        passport_number=MRZField(
            value=pn_raw.replace("<", "").strip(),
            raw=pn_raw,
            checksum_valid=pn_valid,
        ),
        nationality=MRZField(value=nationality_raw.replace("<", ""), raw=nationality_raw),
        date_of_birth=MRZField(
            value=_parse_mrz_date(dob_raw),
            raw=dob_raw,
            checksum_valid=dob_valid,
        ),
        sex=MRZField(value=sex_value, raw=sex_raw),
        expiry_date=MRZField(
            value=_parse_mrz_date(expiry_raw),
            raw=expiry_raw,
            checksum_valid=expiry_valid,
        ),
        personal_number=MRZField(
            value=personal_raw.replace("<", "").strip() or None,
            raw=personal_raw,
            checksum_valid=personal_valid,
        ),
        overall_checksum_valid=overall_valid and pn_valid and dob_valid and expiry_valid,
        raw_lines=(line1, line2),
        errors=errors,
    )
