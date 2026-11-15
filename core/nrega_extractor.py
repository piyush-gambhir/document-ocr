"""Extract identity fields from Indian MGNREGA/NREGA job cards.

The Ministry of Rural Development's MGNREGA Operational Guidelines 2013,
Annexure 5, defines a household-level job-card number, household particulars,
location fields, and a repeating table of adult household members willing to
work.  State-issued cards vary in language and layout, so this extractor is
label- and table-driven rather than tied to one card design.

This module intentionally extracts only the minimum identity/location fields
needed to identify a job card.  Although some card generations also print
Aadhaar, bank/post-office, insurance and voter-card numbers, those high-risk
identifiers are deliberately outside this extractor's contract.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from .ocr_engine import TextRegion


@dataclass
class NregaMember:
    """One adult household member listed as willing to work."""

    serial_number: Optional[str] = None
    name: Optional[str] = None
    father_or_husband_name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None


@dataclass
class NregaFields:
    """Stable household particulars shared by major job-card generations."""

    job_card_number: Optional[str] = None
    head_of_household: Optional[str] = None
    category: Optional[str] = None
    registration_date: Optional[str] = None
    validity_from: Optional[str] = None
    validity_to: Optional[str] = None
    address: Optional[str] = None
    village: Optional[str] = None
    gram_panchayat: Optional[str] = None
    block: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    bpl_status: Optional[bool] = None
    family_id: Optional[str] = None
    members: list[NregaMember] = field(default_factory=list)





_JOB_CARD_LABELS = (
    "JOB CARD NUMBER",
    "JOB CARD NO",
    "JOB CARD",
    "NREGA JOB CARD NO",
    "MGNREGA JOB CARD NO",
    "REGISTRATION NUMBER",
    "REGISTRATION NO",
    "जॉब कार्ड संख्या",
    "जॉब कार्ड क्रमांक",
    "रोजगार कार्ड संख्या",
    "নরেগা জব কার্ড নং",
    "জব কার্ড নং",
    "ఉపాధి హామీ కార్డు సంఖ్య",
    "జాబ్ కార్డ్ నంబర్",
    "வேலை அட்டை எண்",
)
_HEAD_LABELS = (
    "NAME OF HEAD OF HOUSEHOLD",
    "HEAD OF HOUSEHOLD",
    "HOUSEHOLD HEAD NAME",
    "NAME OF APPLICANT",
    "APPLICANT NAME",
    "परिवार के मुखिया का नाम",
    "मुखिया का नाम",
    "परिवार प्रमुख का नाम",
    "পরিবারের প্রধানের নাম",
    "కుటుంబ యజమాని పేరు",
    "குடும்பத் தலைவர் பெயர்",
)
_CATEGORY_LABELS = (
    "CATEGORY",
    "SOCIAL CATEGORY",
    "CASTE CATEGORY",
    "वर्ग",
    "श्रेणी",
    "সামাজিক শ্রেণী",
    "వర్గం",
    "வகை",
)
_REGISTRATION_DATE_LABELS = (
    "DATE OF REGISTRATION",
    "REGISTRATION DATE",
    "DATE OF ISSUE",
    "ISSUE DATE",
    "पंजीकरण की तारीख",
    "पंजीकरण दिनांक",
    "जारी करने की तारीख",
    "নিবন্ধনের তারিখ",
    "నమోదు తేదీ",
    "பதிவு தேதி",
)
_VALIDITY_LABELS = (
    "VALIDITY PERIOD",
    "VALIDITY",
    "वैधता अवधि",
    "বৈধতার সময়কাল",
    "చెల్లుబాటు కాలం",
    "செல்லுபடியாகும் காலம்",
)
_VALID_FROM_LABELS = ("VALID FROM", "FROM", "से", "হইতে", "నుండి", "முதல்")
_VALID_TO_LABELS = ("VALID TO", "TO", "तक", "পর্যন্ত", "వరకు", "வரை")
_ADDRESS_LABELS = (
    "HOUSEHOLD ADDRESS",
    "ADDRESS",
    "पता",
    "घर का पता",
    "ঠিকানা",
    "చిరునామా",
    "முகவரி",
)
_VILLAGE_LABELS = (
    "NAME OF VILLAGE",
    "VILLAGE NAME",
    "VILLAGE",
    "गांव का नाम",
    "गाँव",
    "ग्राम",
    "গ্রাম",
    "గ్రామం",
    "கிராமம்",
)
_PANCHAYAT_LABELS = (
    "NAME OF GRAM PANCHAYAT",
    "GRAM PANCHAYAT",
    "G P NAME",
    "PANCHAYAT",
    "ग्राम पंचायत का नाम",
    "ग्राम पंचायत",
    "পঞ্চায়েত",
    "গ্রাম পঞ্চায়েত",
    "గ్రామ పంచాయతీ",
    "ஊராட்சி",
)
_BLOCK_LABELS = (
    "NAME OF BLOCK",
    "DEVELOPMENT BLOCK",
    "BLOCK",
    "MANDAL",
    "विकास खंड",
    "विकासखण्ड",
    "ब्लॉक",
    "खंड",
    "ব্লক",
    "మండలం",
    "ஒன்றியம்",
    "வட்டாரம்",
)
_DISTRICT_LABELS = (
    "DISTRICT NAME",
    "DISTRICT",
    "जिला",
    "जनपद",
    "জেলা",
    "జిల్లా",
    "மாவட்டம்",
)
_STATE_LABELS = (
    "STATE NAME",
    "STATE",
    "राज्य",
    "প্রদেশ",
    "রাজ্য",
    "రాష్ట్రం",
    "மாநிலம்",
)
_BPL_LABELS = (
    "WHETHER BPL",
    "BPL STATUS",
    "BPL FAMILY",
    "BELOW POVERTY LINE",
    "क्या बीपीएल",
    "बीपीएल परिवार",
    "দারিদ্র্য সীমার নিচে",
    "బిపిఎల్ కుటుంబం",
    "வறுமைக் கோட்டிற்கு கீழ்",
)
_FAMILY_ID_LABELS = (
    "FAMILY ID",
    "FAMILY IDENTIFICATION NUMBER",
    "HOUSEHOLD ID",
    "परिवार आईडी",
    "परिवार पहचान संख्या",
    "পারিবারিক আইডি",
    "కుటుంబ ఐడి",
    "குடும்ப அடையாள எண்",
)

_MEMBER_SECTION_LABELS = (
    "DETAILS OF THE APPLICANTS OF THE HOUSEHOLD WILLING TO WORK",
    "DETAILS OF APPLICANTS",
    "HOUSEHOLD MEMBERS WILLING TO WORK",
    "ADULT MEMBERS WILLING TO WORK",
    "काम करने के इच्छुक परिवार के सदस्यों का विवरण",
    "आवेदकों का विवरण",
    "কাজ করতে ইচ্ছুক সদস্যদের বিবরণ",
    "పని చేయడానికి సిద్ధంగా ఉన్న సభ్యుల వివరాలు",
    "வேலை செய்ய விரும்பும் உறுப்பினர்கள் விவரம்",
)
_SERIAL_HEADER_LABELS = (
    "SL NO",
    "SERIAL NO",
    "S NO",
    "क्रम संख्या",
    "क्र सं",
    "ক্রমিক নং",
    "క్రమ సంఖ్య",
    "வ எண்",
)
_MEMBER_NAME_HEADER_LABELS = (
    "MEMBER NAME",
    "NAME OF MEMBER",
    "NAME OF APPLICANT",
    "NAME",
    "सदस्य का नाम",
    "आवेदक का नाम",
    "नाम",
    "সদস্যের নাম",
    "নাম",
    "సభ్యుని పేరు",
    "పేరు",
    "உறுப்பினர் பெயர்",
    "பெயர்",
)
_RELATION_HEADER_LABELS = (
    "FATHER HUSBAND NAME",
    "FATHERS HUSBANDS NAME",
    "FATHER S HUSBAND S NAME",
    "FATHER OR HUSBAND NAME",
    "PARENT SPOUSE NAME",
    "पिता पति का नाम",
    "पिता या पति का नाम",
    "পিতা স্বামীর নাম",
    "తండ్రి భర్త పేరు",
    "தந்தை கணவர் பெயர்",
)
_GENDER_HEADER_LABELS = (
    "MALE FEMALE",
    "GENDER",
    "SEX",
    "लिंग",
    "पुरुष महिला",
    "লিঙ্গ",
    "స్త్రీ పురుష",
    "లింగం",
    "பாலினம்",
)
_AGE_HEADER_LABELS = (
    "AGE ON DATE OF REGISTRATION",
    "AGE AT REGISTRATION",
    "AGE",
    "पंजीकरण के समय आयु",
    "उम्र",
    "आयु",
    "বয়স",
    "వయస్సు",
    "வயது",
)

_ALL_FIELD_LABEL_GROUPS = (
    _JOB_CARD_LABELS,
    _HEAD_LABELS,
    _CATEGORY_LABELS,
    _REGISTRATION_DATE_LABELS,
    _VALIDITY_LABELS,
    _ADDRESS_LABELS,
    _VILLAGE_LABELS,
    _PANCHAYAT_LABELS,
    _BLOCK_LABELS,
    _DISTRICT_LABELS,
    _STATE_LABELS,
    _BPL_LABELS,
    _FAMILY_ID_LABELS,
    _MEMBER_SECTION_LABELS,
)

_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|"
    r"\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    r"(?:UARY|RUARY|CH|IL|E|Y|UST|TEMBER|OBER|EMBER)?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)




_JOB_CARD_CANDIDATE_RE = re.compile(
    r"(?<![A-Z0-9])("
    r"[A-Z]{2}\s*[-–—]\s*[0-9OILSBZGQD]{1,10}"
    r"(?:\s*[-/–—]\s*[0-9OILSBZGQD]{1,10}){2,7}"
    r")(?![A-Z0-9])",
    re.IGNORECASE,
)
_NUMERIC_OCR_TRANSLATION = str.maketrans(
    {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
     "S": "5", "G": "6", "B": "8"}
)

_MALE_WORDS = {
    "M", "MALE", "MAN", "पुरुष", "नर", "পুরুষ", "ಪುರುಷ", "పురుషుడు",
    "ஆண்",
}
_FEMALE_WORDS = {
    "F", "FEMALE", "WOMAN", "महिला", "स्त्री", "मादा", "মহিলা", "নারী",
    "ಹೆಣ್ಣು", "స్త్రీ", "பெண்",
}
_TRANSGENDER_WORDS = {
    "T", "TG", "TRANSGENDER", "THIRD GENDER", "किन्नर", "ट्रांसजेंडर",
    "তৃতীয় লিঙ্গ", "ట్రాన్స్ జెండర్", "திருநங்கை",
}


def _bounds(region: TextRegion) -> tuple[int, int, int, int]:
    return (
        min(point[0] for point in region.bbox),
        min(point[1] for point in region.bbox),
        max(point[0] for point in region.bbox),
        max(point[1] for point in region.bbox),
    )


def _normalise(text: str, *, label: bool = False) -> str:
    normalised = unicodedata.normalize("NFKC", text).casefold()
    normalised = normalised.replace("&", " and ")
    normalised = re.sub(r"['’`]", "", normalised)



    normalised = "".join(
        character
        if (
            character.isalnum()
            or unicodedata.category(character).startswith(("L", "N", "M"))
        )
        else " "
        for character in normalised
    )
    normalised = " ".join(normalised.split())
    if label:


        normalised = normalised.translate(str.maketrans({"0": "o", "1": "i"}))
    return normalised


def _label_score(text: str, aliases: tuple[str, ...]) -> float:
    """Return a conservative label-match score, including mild OCR noise."""
    candidate = _normalise(text, label=True)
    if not candidate:
        return 0.0



    prefix = re.split(r"\s*[:=]\s*|\s+[–—-]\s+", text, maxsplit=1)[0]
    candidate_prefix = _normalise(prefix, label=True)
    best = 0.0

    for alias in aliases:
        expected = _normalise(alias, label=True)
        if not expected:
            continue
        if candidate == expected or candidate_prefix == expected:
            best = max(best, 1.0 + min(len(expected), 100) / 1000)
            continue
        if f" {expected} " in f" {candidate} ":
            best = max(best, 0.99 + min(len(expected), 100) / 1000)
            continue



        if len(expected) >= 5 and candidate_prefix:
            size_ratio = len(candidate_prefix) / len(expected)
            if 0.65 <= size_ratio <= 1.45:
                ratio = SequenceMatcher(None, candidate_prefix, expected).ratio()
                if ratio >= 0.84:
                    best = max(best, ratio)
    return best


def _best_label_region(
    regions: list[TextRegion], aliases: tuple[str, ...]
) -> Optional[TextRegion]:
    scored = [
        (_label_score(region.text, aliases), region.confidence, region)
        for region in regions
    ]
    scored = [entry for entry in scored if entry[0] >= 0.84]
    if not scored:
        return None
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return scored[0][2]


def _alias_token_count_at_start(text: str, aliases: tuple[str, ...]) -> int:
    tokens = list(re.finditer(r"[^\W_]+", text, flags=re.UNICODE))
    normalised_tokens = [_normalise(token.group(0), label=True) for token in tokens]
    for alias in sorted(aliases, key=lambda value: len(_normalise(value)), reverse=True):
        alias_tokens = _normalise(alias, label=True).split()
        if normalised_tokens[: len(alias_tokens)] == alias_tokens:
            return tokens[len(alias_tokens) - 1].end()
    return 0


def _inline_value(text: str, aliases: tuple[str, ...]) -> Optional[str]:
    for delimiter in (
        re.compile(r"\s*[:=]\s*"),
        re.compile(r"\s+[–—-]\s+"),
    ):
        parts = delimiter.split(text, maxsplit=1)
        if len(parts) == 2 and _label_score(parts[0], aliases) >= 0.84:
            value = parts[1].strip(" :;|")
            return value or None

    end = _alias_token_count_at_start(text, aliases)
    if end:
        value = text[end:].strip(" :;|–—-")
        return value or None
    return None


def _looks_like_known_label(text: str) -> bool:
    return any(_label_score(text, aliases) >= 0.92 for aliases in _ALL_FIELD_LABEL_GROUPS)


def _value_for_labels(
    regions: list[TextRegion], aliases: tuple[str, ...]
) -> Optional[str]:
    label = _best_label_region(regions, aliases)
    if label is None:
        return None

    inline = _inline_value(label.text, aliases)
    if inline:
        return inline

    left, top, right, bottom = _bounds(label)
    height = max(bottom - top, 1)
    right_candidates: list[tuple[float, TextRegion]] = []
    below_candidates: list[tuple[float, TextRegion]] = []

    for region in regions:
        if region is label or _looks_like_known_label(region.text):
            continue
        r_left, r_top, r_right, r_bottom = _bounds(region)
        overlap = min(bottom, r_bottom) - max(top, r_top)
        horizontal_gap = r_left - right
        if overlap >= height * 0.4 and -5 <= horizontal_gap <= 500:
            right_candidates.append((max(horizontal_gap, 0), region))

        vertical_gap = r_top - bottom
        x_overlap = min(right, r_right) - max(left, r_left)
        aligned = abs(r_left - left) <= 220 or x_overlap > 0
        if aligned and -4 <= vertical_gap <= 110:
            below_candidates.append(
                (max(vertical_gap, 0) + abs(r_left - left) * 0.15, region)
            )

    candidates = right_candidates or below_candidates
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (entry[0], -entry[1].confidence))
    value = candidates[0][1].text.strip(" :;|")
    return value or None


def _normalise_job_card_number(text: str) -> Optional[str]:
    text = unicodedata.normalize("NFKC", text).upper()
    matches: list[tuple[int, str]] = []
    for match in _JOB_CARD_CANDIDATE_RE.finditer(text):
        raw = re.sub(r"[–—]", "-", match.group(1))
        parts = re.split(r"([-/])", raw)
        state = parts[0].strip()
        if not re.fullmatch(r"[A-Z]{2}", state):
            continue
        output = [state]
        numeric_components = 0
        for index in range(1, len(parts), 2):
            separator = parts[index]
            raw_component = parts[index + 1].strip()
            component = raw_component.translate(_NUMERIC_OCR_TRANSLATION)
            if not component.isdigit():
                break
            output.extend((separator, component))
            numeric_components += 1
        else:
            if numeric_components >= 3:
                value = "".join(output)
                matches.append((numeric_components, value))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return matches[0][1]


def _find_job_card_number(regions: list[TextRegion]) -> Optional[str]:
    labelled = _value_for_labels(regions, _JOB_CARD_LABELS)
    if labelled:
        value = _normalise_job_card_number(labelled)
        if value:
            return value



    for region in regions:
        value = _normalise_job_card_number(region.text)
        if value:
            return value
    ordered = sorted(regions, key=lambda region: (_bounds(region)[1], _bounds(region)[0]))
    return _normalise_job_card_number(" ".join(region.text for region in ordered))


def _extract_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = _DATE_RE.search(text)
    return match.group(0).strip() if match else None


def _normalise_gender(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    value = _normalise(text)
    if value in {_normalise(word) for word in _TRANSGENDER_WORDS}:
        return "TRANSGENDER"
    if value in {_normalise(word) for word in _FEMALE_WORDS}:
        return "FEMALE"
    if value in {_normalise(word) for word in _MALE_WORDS}:
        return "MALE"
    return None


def _normalise_category(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    value = _normalise(text).upper()
    compact = re.sub(r"[^A-Z]", "", value)
    if compact in {"SC", "SCHEDULEDCASTE"} or "अनुसूचित जाति" in text:
        return "SC"
    if compact in {"ST", "SCHEDULEDTRIBE"} or "अनुसूचित जनजाति" in text:
        return "ST"
    if compact in {"OBC", "OTHERBACKWARDCLASS"} or "अन्य पिछड़ा वर्ग" in text:
        return "OBC"
    if compact in {"OTHER", "OTHERS", "GENERAL", "GEN"}:
        return "OTHER"
    return text.strip() or None


def _normalise_bpl(text: Optional[str]) -> Optional[bool]:
    if not text:
        return None
    value = _normalise(text)
    yes = {
        _normalise(word)
        for word in ("yes", "y", "true", "1", "हाँ", "हां", "জি", "হ্যাঁ", "అవును", "ஆம்")
    }
    no = {
        _normalise(word)
        for word in ("no", "n", "false", "0", "नहीं", "नही", "না", "కాదు", "இல்லை")
    }
    if value in yes or re.search(r"\byes\b", value):
        return True
    if value in no or re.search(r"\bno\b", value):
        return False
    return None


def _parse_age(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"\b(\d{1,3})\b", text)
    if not match:
        return None
    age = int(match.group(1))
    return age if 18 <= age <= 100 else None


def _header_kind(text: str) -> Optional[str]:
    groups = (
        ("serial", _SERIAL_HEADER_LABELS),
        ("relation", _RELATION_HEADER_LABELS),
        ("gender", _GENDER_HEADER_LABELS),
        ("age", _AGE_HEADER_LABELS),
        ("name", _MEMBER_NAME_HEADER_LABELS),
    )
    matches = [
        (kind, _label_score(text, aliases), max(map(len, aliases)))
        for kind, aliases in groups
        if _label_score(text, aliases) >= 0.84
    ]
    if not matches:
        return None

    matches.sort(key=lambda entry: (entry[1], entry[2]), reverse=True)
    return matches[0][0]


def _table_headers(regions: list[TextRegion]) -> dict[str, TextRegion]:
    candidates = [
        (region, _header_kind(region.text))
        for region in regions
        if _header_kind(region.text) is not None
    ]
    best: dict[str, TextRegion] = {}
    best_score = -1

    for anchor, anchor_kind in candidates:
        _, anchor_top, _, anchor_bottom = _bounds(anchor)
        anchor_y = (anchor_top + anchor_bottom) / 2
        clustered: dict[str, TextRegion] = {anchor_kind: anchor}  # type: ignore[dict-item]
        for region, kind in candidates:
            _, top, _, bottom = _bounds(region)
            if abs(((top + bottom) / 2) - anchor_y) <= 38:
                current = clustered.get(kind)  # type: ignore[arg-type]
                if current is None or region.confidence > current.confidence:
                    clustered[kind] = region  # type: ignore[index]
        score = len(clustered) + int("name" in clustered) + int("age" in clustered)
        if "name" in clustered and ("age" in clustered or "gender" in clustered):
            if score > best_score:
                best = clustered
                best_score = score
    return best


def _parse_compact_member_row(text: str) -> Optional[NregaMember]:
    """Parse OCR rows kept as one region, using visible table separators."""
    raw_parts = re.split(r"\s*[|│]\s*|\t+|\s{2,}", text.strip())
    parts = [part.strip(" .:;-") for part in raw_parts if part.strip(" .:;-")]
    if len(parts) < 3:
        return None

    serial: Optional[str] = None
    serial_match = re.fullmatch(r"(\d{1,3})[.)]?", parts[0])
    if serial_match:
        serial = serial_match.group(1)
        parts = parts[1:]

    gender_index = next(
        (index for index, part in enumerate(parts) if _normalise_gender(part)),
        None,
    )
    age_index = next(
        (
            index
            for index, part in enumerate(parts)
            if re.fullmatch(r"(?:AGE\s*[:\-]?\s*)?\d{1,3}", part, re.IGNORECASE)
            and _parse_age(part) is not None
        ),
        None,
    )
    if gender_index is None and age_index is None:
        return None

    control_indexes = [index for index in (gender_index, age_index) if index is not None]
    first_control = min(control_indexes)
    identity_parts = parts[:first_control]
    if not identity_parts:
        return None
    return NregaMember(
        serial_number=serial,
        name=identity_parts[0] or None,
        father_or_husband_name=identity_parts[1] if len(identity_parts) > 1 else None,
        gender=_normalise_gender(parts[gender_index]) if gender_index is not None else None,
        age=_parse_age(parts[age_index]) if age_index is not None else None,
    )


def _members_from_compact_rows(regions: list[TextRegion]) -> list[NregaMember]:
    members = []
    for region in regions:
        member = _parse_compact_member_row(region.text)
        if member and member.name:
            members.append(member)
    return members


def _members_from_table(regions: list[TextRegion]) -> list[NregaMember]:
    headers = _table_headers(regions)
    if not headers:
        return []

    header_bottom = max(_bounds(region)[3] for region in headers.values())
    header_centres = {
        kind: (_bounds(region)[0] + _bounds(region)[2]) / 2
        for kind, region in headers.items()
    }
    min_x = min(_bounds(region)[0] for region in headers.values()) - 80
    max_x = max(_bounds(region)[2] for region in headers.values()) + 220


    stop_y = header_bottom + 520
    for region in regions:
        _, top, _, _ = _bounds(region)
        if top <= header_bottom:
            continue
        if any(
            _label_score(region.text, aliases) >= 0.92
            for aliases in (_ADDRESS_LABELS, _REGISTRATION_DATE_LABELS, _FAMILY_ID_LABELS)
        ):
            stop_y = min(stop_y, top)

    cells = []
    for region in regions:
        if region in headers.values():
            continue
        left, top, right, bottom = _bounds(region)
        centre_x = (left + right) / 2
        if top < header_bottom - 3 or top >= stop_y:
            continue
        if not (min_x <= centre_x <= max_x):
            continue
        if _header_kind(region.text) is not None:
            continue
        cells.append((region, (top + bottom) / 2))

    rows: list[list[TextRegion]] = []
    for region, centre_y in sorted(cells, key=lambda item: (item[1], _bounds(item[0])[0])):
        if not rows:
            rows.append([region])
            continue
        last_centres = [
            (_bounds(item)[1] + _bounds(item)[3]) / 2 for item in rows[-1]
        ]
        if abs(centre_y - sum(last_centres) / len(last_centres)) <= 18:
            rows[-1].append(region)
        else:
            rows.append([region])

    members: list[NregaMember] = []
    for row in rows:
        values: dict[str, str] = {}
        for cell in row:
            left, _, right, _ = _bounds(cell)
            centre_x = (left + right) / 2
            kind = min(header_centres, key=lambda key: abs(header_centres[key] - centre_x))
            existing = values.get(kind)
            values[kind] = (
                f"{existing} {cell.text}".strip() if existing else cell.text.strip()
            )

        serial_match = re.search(r"\b\d{1,3}\b", values.get("serial", ""))
        member = NregaMember(
            serial_number=serial_match.group(0) if serial_match else None,
            name=values.get("name") or None,
            father_or_husband_name=values.get("relation") or None,
            gender=_normalise_gender(values.get("gender")),
            age=_parse_age(values.get("age")),
        )
        if member.name and (member.age is not None or member.gender is not None):
            members.append(member)
    return members


def _deduplicate_members(members: list[NregaMember]) -> list[NregaMember]:
    output: list[NregaMember] = []
    seen: set[tuple[Optional[str], str]] = set()
    for member in members:
        if not member.name:
            continue
        key = (member.serial_number, _normalise(member.name))
        if key in seen:
            continue
        seen.add(key)
        output.append(member)
    return output


def _find_members(regions: list[TextRegion]) -> list[NregaMember]:
    table_members = _members_from_table(regions)
    compact_members = _members_from_compact_rows(regions)
    return _deduplicate_members(table_members + compact_members)


def _find_validity(regions: list[TextRegion]) -> tuple[Optional[str], Optional[str]]:
    validity = _value_for_labels(regions, _VALIDITY_LABELS)
    if validity:
        dates = [match.group(0).strip() for match in _DATE_RE.finditer(validity)]
        if len(dates) >= 2:
            return dates[0], dates[1]

    valid_from = _extract_date(_value_for_labels(regions, _VALID_FROM_LABELS))
    valid_to = _extract_date(_value_for_labels(regions, _VALID_TO_LABELS))
    return valid_from, valid_to


def extract_nrega(regions: list[TextRegion]) -> NregaFields:
    """Extract household and adult-member identity fields from OCR regions."""
    fields = NregaFields()
    fields.job_card_number = _find_job_card_number(regions)
    fields.head_of_household = _value_for_labels(regions, _HEAD_LABELS)
    fields.category = _normalise_category(_value_for_labels(regions, _CATEGORY_LABELS))
    fields.registration_date = _extract_date(
        _value_for_labels(regions, _REGISTRATION_DATE_LABELS)
    )
    fields.validity_from, fields.validity_to = _find_validity(regions)
    fields.address = _value_for_labels(regions, _ADDRESS_LABELS)
    fields.village = _value_for_labels(regions, _VILLAGE_LABELS)
    fields.gram_panchayat = _value_for_labels(regions, _PANCHAYAT_LABELS)
    fields.block = _value_for_labels(regions, _BLOCK_LABELS)
    fields.district = _value_for_labels(regions, _DISTRICT_LABELS)
    fields.state = _value_for_labels(regions, _STATE_LABELS)
    fields.bpl_status = _normalise_bpl(_value_for_labels(regions, _BPL_LABELS))
    fields.family_id = _value_for_labels(regions, _FAMILY_ID_LABELS)
    fields.members = _find_members(regions)
    return fields
