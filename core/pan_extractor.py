"""
Extractor for Indian PAN (Permanent Account Number) cards.

PAN card fields: PAN number, holder name, father's name, date of birth.
Layout has shifted across generations (old NSDL card, e-PAN, QR PAN), but the
labels ("Name", "Father's Name", "Date of Birth") and the PAN format are stable,
so extraction is label- and format-driven rather than position-driven.

Robustness goals (see tests):
  * The PAN number is recognised by *shape* (and preferably holder-type
    validity), never confused with a date or another KYC identifier.
  * ``name`` must never collapse into ``father_name`` — the "Name" label is a
    substring of "Father's Name". We rely on ``find_visual_field``'s
    exact-match priority and additionally de-duplicate the two values.
  * Both the old NSDL "value below the label" layout and the newer e-PAN
    "Label : value on the same row" layout are handled.
  * Bilingual Hindi/English noise rows and missing labels are tolerated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ocr_engine import TextRegion
from .validator import find_label_value, find_visual_field
from .validators import is_valid_pan, normalize_pan

# A printed PAN-card date: DD/MM/YYYY or DD-MM-YYYY (also tolerates "." and a
# 2-digit year). The PAN itself never contains these separators, so a date can
# never be mistaken for a PAN and vice-versa.
_DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b")

# Label vocabularies. ``find_visual_field`` normalises OCR noise (case,
# punctuation, "&" -> "AND") and favours exact phrase matches, so we list the
# most specific spellings first.
_NAME_LABELS = [
    "NAME",
    "NAME OF THE CARDHOLDER",
    "CARDHOLDER NAME",
    "CARD HOLDER NAME",
]
_FATHER_LABELS = [
    "FATHER S NAME",
    "FATHERS NAME",
    "FATHER NAME",
    "NAME OF FATHER",
    "PARENT S NAME",
    "PARENTS NAME",
    "NAME OF PARENT",
]
_DOB_LABELS = [
    "DATE OF BIRTH",
    "DATE OF BIRTH INCORPORATION",
    "DATE OF BIRTH OR INCORPORATION",
    "DOB",
]


@dataclass
class PanFields:
    pan_number: Optional[str] = None
    name: Optional[str] = None
    father_name: Optional[str] = None
    date_of_birth: Optional[str] = None


# ---------------------------------------------------------------------------
# PAN number
# ---------------------------------------------------------------------------

def _find_pan_number(regions: list[TextRegion]) -> Optional[str]:
    """Locate the PAN by shape, preferring a holder-type-valid token.

    Strategy, best-first:
      1. A region adjacent to a "Permanent Account Number" / "PAN" label whose
         text yields a *valid* PAN (correct 4th holder-type character).
      2. Any region yielding a *valid* PAN.
      3. Any region yielding a merely PAN-*shaped* token (tolerates OCR noise
         in the holder-type position).

    ``normalize_pan`` uses ``re.search`` over the alnum-compacted text, so dates
    (which carry separators) and other KYC ids (e.g. a 15-char DL number) can
    never be sliced into a false PAN.
    """
    labelled = find_label_value(
        regions, ["PERMANENT ACCOUNT NUMBER", "PERMANENT ACCOUNT NUMBER CARD", "PAN"]
    )
    if labelled and is_valid_pan(labelled):
        pan = normalize_pan(labelled)
        if pan:
            return pan

    shaped_fallback: Optional[str] = None
    for region in regions:
        pan = normalize_pan(region.text)
        if pan is None:
            continue
        if is_valid_pan(region.text):
            return pan
        if shaped_fallback is None:
            shaped_fallback = pan
    return shaped_fallback


# ---------------------------------------------------------------------------
# Date of birth
# ---------------------------------------------------------------------------

def _find_date(regions: list[TextRegion]) -> Optional[str]:
    """Prefer a date adjacent to a DOB label; fall back to the first date.

    DOB is left as the printed string (DD/MM/YYYY or DD-MM-YYYY) — see the
    module/report notes: no ISO normalisation, to keep downstream values and
    the TypeScript types unchanged.
    """
    labelled = find_label_value(regions, _DOB_LABELS)
    if labelled:
        m = _DATE_RE.search(labelled)
        if m:
            return m.group(1)

    for region in regions:
        m = _DATE_RE.search(region.text)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Name / father's name
# ---------------------------------------------------------------------------

def _clean_value(text: Optional[str]) -> Optional[str]:
    """Strip leftover label punctuation/whitespace from a resolved value."""
    if text is None:
        return None
    # Drop a leading "value-side" colon that occasionally rides along when the
    # label and value were merged or mis-split by OCR (e.g. ": ROHIT SHARMA").
    cleaned = text.strip().lstrip(":").strip()
    return cleaned or None


def _resolve_names(regions: list[TextRegion]) -> tuple[Optional[str], Optional[str]]:
    """Resolve (name, father_name) ensuring ``name`` never collapses into it.

    The "Name" label is a substring of "Father's Name", so a naive lookup can
    bind ``name`` to the father's value when the dedicated "Name" label is
    absent or mis-OCR'd. We therefore:
      * locate the father's-name label region first and exclude it (and its
        resolved value) when resolving the plain "Name" label, and
      * if both labels resolve to the *same* value, treat the plain-name lookup
        as a false positive and drop it.
    """
    father_value = _clean_value(find_label_value(regions, _FATHER_LABELS))

    name_value = _clean_value(find_label_value(regions, _NAME_LABELS))

    # Guard against the substring collapse: if the "Name" lookup latched onto
    # the father's-name label/value, discard it rather than duplicate.
    if name_value is not None and name_value == father_value:
        # Make sure we did not simply read the same label region. Re-resolve the
        # plain-name label and confirm it is a distinct region from the father
        # label before trusting the duplicate; otherwise drop the name.
        name_label = find_visual_field(regions, _NAME_LABELS)
        father_label = find_visual_field(regions, _FATHER_LABELS)
        if name_label is None or name_label is father_label:
            name_value = None

    return name_value, father_value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_pan(regions: list[TextRegion]) -> PanFields:
    fields = PanFields()
    fields.pan_number = _find_pan_number(regions)
    fields.name, fields.father_name = _resolve_names(regions)
    fields.date_of_birth = _find_date(regions)
    return fields
