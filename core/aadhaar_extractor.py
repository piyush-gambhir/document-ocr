"""
Extractor for Indian Aadhaar cards (front and back).

Front fields: Aadhaar number, name, date/year of birth, gender.
Back fields:  address, pincode.

Aadhaar has no Latin field labels for the name (it sits above the DOB line), so
the name is found spatially relative to the DOB/gender block. The Aadhaar number
and its Verhoeff checksum are handled in core.validators.

Robustness notes:
  * VID (a 16-digit Virtual ID, grouped 4-4-4-4) is masked out of the text
    before the 12-digit Aadhaar is extracted, otherwise the VID's first twelve
    digits would be mis-captured as the Aadhaar number.
  * Masked Aadhaar ("XXXX XXXX 9012") is recognised: the visible tail is
    surfaced via ``aadhaar_masked`` / ``aadhaar_last4`` and ``checksum_valid``
    stays False (we never crash on a missing/partial number).
  * Gender is normalised across English and Hindi (Devanagari) spellings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ocr_engine import TextRegion
from .validator import find_label_value, find_visual_field
from .validators import extract_aadhaar_number, is_valid_aadhaar

_DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})\b")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_PINCODE_RE = re.compile(r"\b(\d{6})\b")

# A Virtual ID is 16 digits, printed grouped 4-4-4-4 (optionally spaced) — or as
# a bare 16-digit run. Either form must be removed before Aadhaar extraction.
_VID_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b")
_VID_LABEL_RE = re.compile(r"\bVID\b", re.IGNORECASE)

# Masked Aadhaar: leading groups are X'd out and only the final 4 digits show,
# e.g. "XXXX XXXX 9012" / "xxxxxxxx9012" / "**** **** 9012".
_MASKED_AADHAAR_RE = re.compile(
    r"(?:[Xx*]{4}[\s-]?){2}(\d{4})\b"
)

_GENDER_WORDS = {
    "MALE": "MALE",
    "FEMALE": "FEMALE",
    "TRANSGENDER": "TRANSGENDER",
}

# Hindi (Devanagari) gender words map to the same canonical values.
_GENDER_HINDI = {
    "पुरुष": "MALE",
    "महिला": "FEMALE",
    "स्त्री": "FEMALE",
    "किन्नर": "TRANSGENDER",
    "ट्रांसजेंडर": "TRANSGENDER",
}

# Header / label noise that must never be mistaken for the holder name.
_NAME_STOPWORDS = {
    "GOVERNMENT", "GOVT", "INDIA", "BHARAT", "AADHAAR", "AADHAR", "UNIQUE",
    "IDENTIFICATION", "AUTHORITY", "UIDAI", "MALE", "FEMALE", "TRANSGENDER",
    "DOB", "YEAR", "BIRTH", "YOB", "ADDRESS", "MOBILE", "VID", "ENROLLMENT",
    "ENROLMENT", "GENDER", "DATE", "NUMBER", "CARD", "DOWNLOAD", "ISSUE",
    "ISSUED", "HELP", "EMAIL", "WWW", "PHONE", "MERA", "AADHAR", "VALID",
}

# Care-of prefixes that introduce the address on the back.
_CARE_OF_RE = re.compile(r"\b([SCDWscdw])\s*/\s*[Oo]\b")


@dataclass
class AadhaarFields:
    aadhaar_number: Optional[str] = None
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    year_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    checksum_valid: bool = False
    # --- additive fields (do not rename existing ones) ---
    aadhaar_masked: bool = False
    aadhaar_last4: Optional[str] = None
    vid: Optional[str] = None


def _devanagari_ratio(text: str) -> float:
    """Fraction of alphabetic characters that fall in the Devanagari block."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    devanagari = sum(1 for c in letters if "ऀ" <= c <= "ॿ")
    return devanagari / len(letters)


def _is_name_like(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 3 or any(ch.isdigit() for ch in stripped):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    # Mostly Latin letters (Aadhaar prints the name in English too).
    if _devanagari_ratio(stripped) > 0.5:
        return False
    if sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.5:
        return False
    # A care-of address line ("S/O ...") is not the holder name.
    if _CARE_OF_RE.search(stripped):
        return False
    words = re.sub(r"[^A-Z ]", " ", stripped.upper()).split()
    if not words:
        return False
    return not any(w in _NAME_STOPWORDS for w in words)


def _find_gender(regions: list[TextRegion]) -> Optional[str]:
    for region in regions:
        text = region.text
        # English / Latin gender words, matched as whole words.
        upper = re.sub(r"[^A-Z]", " ", text.upper())
        padded = f" {upper} "
        for word, value in _GENDER_WORDS.items():
            if f" {word} " in padded:
                return value
        # Hindi (Devanagari) gender words.
        for word, value in _GENDER_HINDI.items():
            if word in text:
                return value
    return None


def _find_dob_region(regions: list[TextRegion]) -> Optional[TextRegion]:
    """Locate the region carrying the date/year of birth.

    Prefer a region that both mentions a DOB/birth label *and* carries a date;
    fall back to any birth-labelled region, then to any bare date region.
    """
    labelled_with_date: Optional[TextRegion] = None
    labelled: Optional[TextRegion] = None
    bare_date: Optional[TextRegion] = None

    for region in regions:
        upper = region.text.upper()
        has_birth_label = (
            "DOB" in upper
            or "YEAR OF BIRTH" in upper
            or "YOB" in upper
            or "BIRTH" in upper
            or "जन्म" in region.text  # Hindi "janm" (birth)
        )
        has_date = bool(_DATE_RE.search(region.text))
        if has_birth_label and has_date and labelled_with_date is None:
            labelled_with_date = region
        elif has_birth_label and labelled is None:
            labelled = region
        elif has_date and bare_date is None:
            bare_date = region

    return labelled_with_date or labelled or bare_date


def _find_name(
    regions: list[TextRegion],
    dob_region: Optional[TextRegion],
    *,
    is_front: bool,
) -> Optional[str]:
    candidates = [r for r in regions if _is_name_like(r.text)]
    if not candidates:
        return None
    if dob_region is not None:
        dob_top = min(p[1] for p in dob_region.bbox)
        dob_left = min(p[0] for p in dob_region.bbox)
        above = [r for r in candidates if max(p[1] for p in r.bbox) <= dob_top + 5]
        if above:
            # Closest line above the DOB, breaking ties by horizontal proximity.
            above.sort(
                key=lambda r: (
                    dob_top - max(p[1] for p in r.bbox),
                    abs(min(p[0] for p in r.bbox) - dob_left),
                )
            )
            return above[0].text.strip()
    # No DOB anchor: only guess a name on a front page (a back/address page has
    # no holder name, and address/locality lines must not be fabricated as one).
    if not is_front:
        return None
    # Fall back to the topmost name-like line (the "Government of India" band is
    # already filtered out by the stopword list).
    candidates.sort(key=lambda r: min(p[1] for p in r.bbox))
    return candidates[0].text.strip()


def _find_address(regions: list[TextRegion]) -> Optional[str]:
    label = find_visual_field(regions, ["ADDRESS", "पता"])
    if label is None:
        return None
    label_bottom = max(p[1] for p in label.bbox)
    label_top = min(p[1] for p in label.bbox)
    lines = []
    for region in regions:
        if region is label:
            continue
        top = min(p[1] for p in region.bbox)
        bottom = max(p[1] for p in region.bbox)
        # Keep lines that begin at/below the label and within a reasonable span.
        # Also allow a line that shares the label's row (inline "Address: ...").
        on_label_row = bottom > label_top and top < label_bottom
        if not on_label_row and (top < label_bottom - 10 or top - label_bottom > 300):
            continue
        text = region.text.strip()
        if _devanagari_ratio(text) > 0.5:
            continue  # skip mostly-Devanagari noise lines
        # Skip a standalone Aadhaar/VID number line printed below the address.
        if not any(c.isalpha() for c in text) and sum(c.isdigit() for c in text) >= 8:
            continue
        if len(text) >= 2:
            lines.append((top, text))
    lines.sort(key=lambda x: x[0])
    if not lines:
        # Address may be on the same line as the label ("Address: ...").
        inline = find_label_value(regions, ["ADDRESS"])
        return inline
    return ", ".join(text for _, text in lines[:6])


def _strip_vid(text: str) -> tuple[str, Optional[str]]:
    """Remove 16-digit VID sequences from ``text`` and return (cleaned, vid).

    Both spaced ("9148 6541 8231 2156") and bare ("9148654182312156") 16-digit
    forms are stripped so the downstream 12-digit Aadhaar matcher cannot slice
    the VID's leading twelve digits. The first VID found is surfaced.
    """
    found: Optional[str] = None

    def _replace(match: re.Match[str]) -> str:
        nonlocal found
        if found is None:
            digits = re.sub(r"\D", "", match.group(0))
            found = f"{digits[0:4]} {digits[4:8]} {digits[8:12]} {digits[12:16]}"
        return " "

    cleaned = _VID_RE.sub(_replace, text)
    return cleaned, found


def extract_aadhaar(regions: list[TextRegion]) -> AadhaarFields:
    fields = AadhaarFields()
    joined = " ".join(r.text for r in regions if r.text.strip())

    # Strip any 16-digit VID first so it can't be misread as the Aadhaar number.
    cleaned, fields.vid = _strip_vid(joined)

    fields.aadhaar_number = extract_aadhaar_number(cleaned)
    fields.checksum_valid = is_valid_aadhaar(cleaned)

    # Masked Aadhaar handling: when no full number is present but a masked form
    # ("XXXX XXXX 9012") is, surface the visible tail without claiming validity.
    if fields.aadhaar_number is None:
        masked = _MASKED_AADHAAR_RE.search(cleaned)
        if masked:
            fields.aadhaar_masked = True
            fields.aadhaar_last4 = masked.group(1)
    elif fields.aadhaar_number:
        fields.aadhaar_last4 = fields.aadhaar_number.split()[-1]

    fields.gender = _find_gender(regions)

    dob_region = _find_dob_region(regions)
    if dob_region is not None:
        date_match = _DATE_RE.search(dob_region.text)
        if date_match:
            fields.date_of_birth = date_match.group(1)
        else:
            year_match = _YEAR_RE.search(dob_region.text)
            if year_match:
                fields.year_of_birth = year_match.group(1)

    # A page is "front-like" when it carries a DOB/year or a gender word, and is
    # not an address (back) page. The name heuristic only fabricates a fallback
    # name on front-like pages.
    has_address_label = find_visual_field(regions, ["ADDRESS", "पता"]) is not None
    is_front = (
        dob_region is not None or fields.gender is not None
    ) and not has_address_label
    fields.name = _find_name(regions, dob_region, is_front=is_front)

    address = _find_address(regions)
    if address:
        fields.address = address
        pincode = _PINCODE_RE.search(address)
        fields.pincode = pincode.group(1) if pincode else None

    return fields
