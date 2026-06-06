"""
Extractor for Indian Voter ID (EPIC / Elector's Photo Identity Card) cards.

Fields: EPIC number, elector name, relation (father's/husband's/mother's) name,
relation type, gender, date of birth or age.

Robust against the real-world variation seen on these cards:

  * Old laminated cards and new PVC cards, bilingual Hindi/English labels.
  * EPIC number anywhere on the card (validated via core.validators.normalize_epic).
  * "Elector's Name" / "Name" for the holder vs "Father's Name" /
    "Husband's Name" / "Mother's Name" for the relation — the two must never
    collapse into one another.
  * Value laid out to the right of the label ("Name : X") or below it.
  * Gender given as M / F / Male / Female or Hindi पुरुष / महिला, possibly only
    as a bare value with a Hindi-only ("लिंग") label.
  * "Date of Birth" when present, otherwise "Age as on 1.1.YYYY" / "Age".

The EPIC number format is validated in core.validators. This module only reads
from core.validator / core.validators helpers — it does not mutate any shared
state.
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
from .validators import normalize_epic

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# dd/mm/yyyy (also tolerates '.' or '-' separators and 2-digit years).
_DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b")

# "Age as on 1.1.2024 : 34" / "Age 34" / "Age : 34". We deliberately anchor on
# the word AGE and take the *last* small integer on the fragment so the year in
# "as on 1.1.2024" is never mistaken for the age.
_AGE_LABEL_RE = re.compile(r"\bAGE\b", re.IGNORECASE)
_SMALL_INT_RE = re.compile(r"\b(\d{1,3})\b")

# ---------------------------------------------------------------------------
# Label vocabularies (English; Hindi handled separately/spatially)
# ---------------------------------------------------------------------------

# Holder-name labels. Ordered most-specific first; find_visual_field scores
# exact/whole-phrase matches above generic substrings, so the specific
# "ELECTOR'S NAME" wins over a bare "NAME" when both are present.
_NAME_LABELS = [
    "ELECTOR S NAME",
    "ELECTORS NAME",
    "ELECTOR NAME",
    "NAME OF ELECTOR",
    "NAME",
]

# Relation labels split by type so we can report relation_type.
_FATHER_LABELS = [
    "FATHER S NAME", "FATHERS NAME", "FATHER NAME", "NAME OF FATHER", "FATHER",
]
_HUSBAND_LABELS = [
    "HUSBAND S NAME", "HUSBANDS NAME", "HUSBAND NAME", "NAME OF HUSBAND", "HUSBAND",
]
_MOTHER_LABELS = [
    "MOTHER S NAME", "MOTHERS NAME", "MOTHER NAME", "NAME OF MOTHER", "MOTHER",
]

_GENDER_LABELS = ["SEX", "GENDER"]
_DOB_LABELS = ["DATE OF BIRTH", "DOB"]
_AGE_LABELS = ["AGE AS ON", "AGE"]

# Tokens that indicate a region is a label / header, not a value, when we fall
# back to scanning for a bare gender value.
_GENDER_VALUE_TOKENS = {"MALE", "FEMALE", "TRANSGENDER", "M", "F", "T"}
_HINDI_MALE = "पुरुष"
_HINDI_FEMALE = "महिला"
_HINDI_TRANS = "अन्य"


@dataclass
class VoterIdFields:
    epic_number: Optional[str] = None
    name: Optional[str] = None
    relation_name: Optional[str] = None
    # NEW: "father" / "husband" / "mother" when the relation label is identifiable.
    relation_type: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    age: Optional[str] = None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _ascii_letters(text: str) -> str:
    return re.sub(r"[^A-Z]", "", text.upper())


def _is_relation_label(text: str) -> bool:
    """True if the region text looks like a father/husband/mother label."""
    letters = _ascii_letters(text)
    return any(tok in letters for tok in ("FATHER", "HUSBAND", "MOTHER"))


def _clean_value(text: Optional[str]) -> Optional[str]:
    """Trim a value and strip a leading 'Label :' fragment / stray punctuation."""
    if not text:
        return None
    value = text.strip()
    # Drop a leading "... :" colon-prefixed label fragment that some OCR runs glue
    # onto the value region (e.g. "Name : DEEPAK MEHTA").
    if ":" in value:
        tail = value.split(":")[-1].strip()
        if tail:
            value = tail
    value = value.strip(" :,-")
    return value or None


def _find_epic(regions: list[TextRegion]) -> Optional[str]:
    """First EPIC-shaped token anywhere on the card."""
    for region in regions:
        epic = normalize_epic(region.text)
        if epic:
            return epic
    return None


# ---------------------------------------------------------------------------
# Name vs relation disambiguation
# ---------------------------------------------------------------------------

def _find_holder_name(regions: list[TextRegion]) -> Optional[str]:
    """Resolve the elector's own name without collapsing into the relation name.

    `find_visual_field` matches a bare "NAME" against "FATHER'S NAME" too, so we
    locate the label region ourselves and reject it if it is actually a relation
    label, then read the value to its right (or below).
    """
    label = find_visual_field(regions, _NAME_LABELS)
    if label is None:
        return None
    # If the only "NAME" match is a relation label, there is no usable holder
    # name label — bail rather than returning the relation's value.
    if _is_relation_label(label.text):
        return None
    value = find_visual_value_right(regions, label) or find_visual_value_near(
        regions, label
    )
    if value is None:
        return None
    # Guard: the resolved value must not itself be a relation label or the
    # relation value bleeding up/down.
    if _is_relation_label(value.text):
        return None
    return _clean_value(value.text)


def _find_relation(regions: list[TextRegion]) -> tuple[Optional[str], Optional[str]]:
    """Return (relation_name, relation_type) from father/husband/mother labels."""
    for labels, rtype in (
        (_FATHER_LABELS, "father"),
        (_HUSBAND_LABELS, "husband"),
        (_MOTHER_LABELS, "mother"),
    ):
        label = find_visual_field(regions, labels)
        if label is None:
            continue
        # find_visual_field can match the wrong-family label via a shared "NAME"
        # token; require the chosen label to actually contain the relation word.
        if not _is_relation_label(label.text):
            continue
        letters = _ascii_letters(label.text)
        if rtype.upper() not in letters:
            continue
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is None:
            continue
        cleaned = _clean_value(value.text)
        if cleaned:
            return cleaned, rtype
    return None, None


# ---------------------------------------------------------------------------
# Gender
# ---------------------------------------------------------------------------

def _normalise_gender(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    upper = text.upper()
    # Whole-word / substring checks on the ASCII form.
    if "FEMALE" in upper:
        return "FEMALE"
    if "MALE" in upper:
        return "MALE"
    if "TRANSGENDER" in upper or "OTHER" in upper:
        return "TRANSGENDER"
    # Hindi.
    if _HINDI_FEMALE in text:
        return "FEMALE"
    if _HINDI_MALE in text:
        return "MALE"
    if _HINDI_TRANS in text:
        return "TRANSGENDER"
    # Bare single-letter codes.
    letters = _ascii_letters(text)
    if letters == "F":
        return "FEMALE"
    if letters == "M":
        return "MALE"
    if letters == "T":
        return "TRANSGENDER"
    return None


def _scan_gender(regions: list[TextRegion]) -> Optional[str]:
    """Fallback: find a region whose text *is* a gender value.

    Used when the gender label is Hindi-only (so find_visual_field can't see it)
    or the value sits without a recoverable English label.
    """
    for region in regions:
        text = region.text.strip()
        # Hindi value regions.
        if _HINDI_FEMALE in text or _HINDI_MALE in text or _HINDI_TRANS in text:
            g = _normalise_gender(text)
            if g:
                return g
        letters = _ascii_letters(text)
        if letters in _GENDER_VALUE_TOKENS:
            g = _normalise_gender(text)
            if g:
                return g
    return None


def _find_gender(regions: list[TextRegion]) -> Optional[str]:
    # 1) Label-driven (Sex / Gender → value right/below).
    labelled = _normalise_gender(find_label_value(regions, _GENDER_LABELS))
    if labelled:
        return labelled
    # 2) Spatial: a "Sex"/"Gender" label whose value we read directly.
    label = find_visual_field(regions, _GENDER_LABELS)
    if label is not None:
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            g = _normalise_gender(value.text)
            if g:
                return g
    # 3) Content scan (Hindi-only label, or bare M/F/पुरुष/महिला token).
    return _scan_gender(regions)


# ---------------------------------------------------------------------------
# Date of birth / age
# ---------------------------------------------------------------------------

def _find_dob(regions: list[TextRegion]) -> Optional[str]:
    """A dd/mm/yyyy date tied to a DOB label, else the first plausible date."""
    labelled = find_label_value(regions, _DOB_LABELS)
    if labelled:
        m = _DATE_RE.search(labelled)
        if m:
            return m.group(1)
    # Spatial read of the DOB label's neighbour (value may be a separate region).
    label = find_visual_field(regions, _DOB_LABELS)
    if label is not None:
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            m = _DATE_RE.search(value.text)
            if m:
                return m.group(1)
    return None


def _find_age(regions: list[TextRegion], joined: str) -> Optional[str]:
    """Integer age from an 'Age'/'Age as on ...' label or fragment.

    Resilient to "Age as on 1.1.2024 : 34" by ignoring the date-like year and
    taking the trailing small integer; also handles a separate value region.
    """
    # Label-driven, value to the right / below.
    label = find_visual_field(regions, _AGE_LABELS)
    if label is not None and "AGE" in _ascii_letters(label.text):
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            age = _age_from_fragment(value.text)
            if age:
                return age
        # Age may be glued onto the label region itself ("Age : 34").
        age = _age_from_fragment(label.text)
        if age:
            return age
    # Whole-card fallback: scan each region containing the word AGE.
    for region in regions:
        if _AGE_LABEL_RE.search(region.text):
            age = _age_from_fragment(region.text)
            if age:
                return age
    # Last resort: the joined text (handles age split oddly across regions).
    m = _AGE_LABEL_RE.search(joined)
    if m:
        age = _age_from_fragment(joined[m.start():])
        if age:
            return age
    return None


def _age_from_fragment(text: str) -> Optional[str]:
    """Extract an age integer from a fragment, skipping any embedded date.

    "Age as on 1.1.2024 : 34" → "34"; "Age 34" → "34"; "34" → "34".
    """
    # Remove any dd/mm/yyyy-style date so its components aren't read as the age.
    without_dates = _DATE_RE.sub(" ", text)
    # Also remove bare 4-digit years that survive (e.g. "as on 2024").
    without_years = re.sub(r"\b(19|20)\d{2}\b", " ", without_dates)
    ints = _SMALL_INT_RE.findall(without_years)
    for candidate in ints:
        n = int(candidate)
        if 1 <= n <= 120:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_voter_id(regions: list[TextRegion]) -> VoterIdFields:
    fields = VoterIdFields()
    joined = " ".join(r.text for r in regions if r.text.strip())

    fields.epic_number = _find_epic(regions)
    fields.name = _find_holder_name(regions)
    fields.relation_name, fields.relation_type = _find_relation(regions)
    fields.gender = _find_gender(regions)

    dob = _find_dob(regions)
    if dob:
        fields.date_of_birth = dob
    else:
        fields.age = _find_age(regions, joined)

    return fields
