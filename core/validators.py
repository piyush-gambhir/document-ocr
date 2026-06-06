"""
Format and checksum validators for Indian KYC document identifiers.

Kept separate from the passport MRZ checksum (core/mrz_parser.icao_check_digit)
because these documents use different identifier schemes:

  * PAN     — fixed alphanumeric format (no checksum that is publicly verifiable)
  * Aadhaar — 12 digits, last digit a Verhoeff checksum over the first 11
  * EPIC    — 3 letters + 7 digits (Voter ID)
  * DL      — state code + RTO + year + serial (format varies; loose check)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# PAN — Permanent Account Number
# Format: 5 letters + 4 digits + 1 letter, e.g. ABCDE1234F.
# The 4th letter encodes holder type (P=individual, C=company, ...).
# ---------------------------------------------------------------------------

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_PAN_HOLDER_TYPES = set("ABCFGHLJPTK")


def normalize_pan(text: str) -> str | None:
    """Extract a PAN-shaped token from noisy OCR text, or None."""
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    match = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", compact)
    return match.group(0) if match else None


def is_valid_pan(text: str) -> bool:
    pan = normalize_pan(text)
    if pan is None:
        return False
    return bool(_PAN_RE.match(pan)) and pan[3] in _PAN_HOLDER_TYPES


# ---------------------------------------------------------------------------
# EPIC — Voter ID (Elector's Photo Identity Card)
# Format: 3 letters + 7 digits, e.g. ABC1234567.
# ---------------------------------------------------------------------------

_EPIC_RE = re.compile(r"^[A-Z]{3}[0-9]{7}$")


def normalize_epic(text: str) -> str | None:
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    match = re.search(r"[A-Z]{3}[0-9]{7}", compact)
    return match.group(0) if match else None


def is_valid_epic(text: str) -> bool:
    epic = normalize_epic(text)
    return epic is not None and bool(_EPIC_RE.match(epic))


# ---------------------------------------------------------------------------
# Driving Licence
# Format varies by state, but most follow: 2-letter state code, 2-digit RTO,
# optional space, then 11 digits (often YYYY + 7-digit serial), e.g.
#   MH1220110012345, DL0420110149646, HR-06 19850034761.
# We accept a loose shape and surface the compact form.
# ---------------------------------------------------------------------------

_DL_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[0-9]{11}$")


def normalize_dl(text: str) -> str | None:
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    match = re.search(r"[A-Z]{2}[0-9]{2}[0-9]{11}", compact)
    return match.group(0) if match else None


def is_valid_dl(text: str) -> bool:
    dl = normalize_dl(text)
    return dl is not None and bool(_DL_RE.match(dl))


# ---------------------------------------------------------------------------
# Aadhaar — 12 digits, 12th digit is a Verhoeff checksum over the first 11.
# ---------------------------------------------------------------------------

# Verhoeff algorithm tables (dihedral group D5).
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_validate(number: str) -> bool:
    """True if the digit string passes the Verhoeff checksum (check digit included)."""
    if not number.isdigit():
        return False
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(digit)]]
    return c == 0


_AADHAAR_DIGITS_RE = re.compile(r"\b(\d{4})\s?(\d{4})\s?(\d{4})\b")


def extract_aadhaar_number(text: str) -> str | None:
    """Find a 12-digit Aadhaar number in text and return it grouped 'XXXX XXXX XXXX'."""
    match = _AADHAAR_DIGITS_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)} {match.group(3)}"


def is_valid_aadhaar(text: str) -> bool:
    grouped = extract_aadhaar_number(text)
    if grouped is None:
        return False
    digits = grouped.replace(" ", "")
    # Aadhaar never starts with 0 or 1.
    if digits[0] in "01":
        return False
    return verhoeff_validate(digits)
