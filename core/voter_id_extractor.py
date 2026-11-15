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






_DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\b")




_AGE_LABEL_RE = re.compile(r"\bAGE\b", re.IGNORECASE)
_SMALL_INT_RE = re.compile(r"\b(\d{1,3})\b")








_NAME_LABELS = [
    "ELECTOR S NAME",
    "ELECTORS NAME",
    "ELECTOR NAME",
    "NAME OF ELECTOR",
    "NAME",
]


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



_GENDER_VALUE_TOKENS = {"MALE", "FEMALE", "TRANSGENDER", "M", "F", "T"}
_HINDI_MALE = "पुरुष"
_HINDI_FEMALE = "महिला"
_HINDI_TRANS = "अन्य"


@dataclass
class VoterIdFields:
    epic_number: Optional[str] = None
    name: Optional[str] = None
    relation_name: Optional[str] = None

    relation_type: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    age: Optional[str] = None






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






def _find_holder_name(regions: list[TextRegion]) -> Optional[str]:
    """Resolve the elector's own name without collapsing into the relation name.

    `find_visual_field` matches a bare "NAME" against "FATHER'S NAME" too, so we
    locate the label region ourselves and reject it if it is actually a relation
    label, then read the value to its right (or below).
    """
    label = find_visual_field(regions, _NAME_LABELS)
    if label is None:
        return None


    if _is_relation_label(label.text):
        return None
    value = find_label_value(regions, _NAME_LABELS)
    if value is None:
        return None


    if _is_relation_label(value):
        return None
    return _clean_value(value)


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


        if not _is_relation_label(label.text):
            continue
        letters = _ascii_letters(label.text)
        if rtype.upper() not in letters:
            continue
        value = find_label_value(regions, labels)
        if value is None:
            continue
        cleaned = _clean_value(value)
        if cleaned:
            return cleaned, rtype
    return None, None






def _normalise_gender(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    upper = text.upper()

    if "FEMALE" in upper:
        return "FEMALE"
    if "MALE" in upper:
        return "MALE"
    if "TRANSGENDER" in upper or "OTHER" in upper:
        return "TRANSGENDER"

    if _HINDI_FEMALE in text:
        return "FEMALE"
    if _HINDI_MALE in text:
        return "MALE"
    if _HINDI_TRANS in text:
        return "TRANSGENDER"

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

    labelled = _normalise_gender(find_label_value(regions, _GENDER_LABELS))
    if labelled:
        return labelled

    label = find_visual_field(regions, _GENDER_LABELS)
    if label is not None:
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            g = _normalise_gender(value.text)
            if g:
                return g

    return _scan_gender(regions)






def _find_dob(regions: list[TextRegion]) -> Optional[str]:
    """A dd/mm/yyyy date tied to a DOB label, else the first plausible date."""
    labelled = find_label_value(regions, _DOB_LABELS)
    if labelled:
        m = _DATE_RE.search(labelled)
        if m:
            return m.group(1)

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

    label = find_visual_field(regions, _AGE_LABELS)
    if label is not None and "AGE" in _ascii_letters(label.text):
        value = find_visual_value_right(regions, label) or find_visual_value_near(
            regions, label
        )
        if value is not None:
            age = _age_from_fragment(value.text)
            if age:
                return age

        age = _age_from_fragment(label.text)
        if age:
            return age

    for region in regions:
        if _AGE_LABEL_RE.search(region.text):
            age = _age_from_fragment(region.text)
            if age:
                return age

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

    without_dates = _DATE_RE.sub(" ", text)

    without_years = re.sub(r"\b(19|20)\d{2}\b", " ", without_dates)
    ints = _SMALL_INT_RE.findall(without_years)
    for candidate in ints:
        n = int(candidate)
        if 1 <= n <= 120:
            return candidate
    return None






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
