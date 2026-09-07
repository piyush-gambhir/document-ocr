"""Strict TD1 and machine-readable visa extraction, with US card profiles.

Field positions follow ICAO Doc 9303 parts 5 and 7. USCIS cards expose an
A-number in the main number field and a separate card number in optional data;
these are intentionally not mapped to the same public field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document_registry import normalize_country
from .mrz_parser import _DIGIT_CORRECTIONS, _parse_mrz_date, verify_check_digit
from .ocr_engine import TextRegion


@dataclass
class TravelMRZResult:
    document_type: str
    issuing_country: str | None
    fields: dict
    field_evidence: dict
    checks: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _name(text: str) -> str:
    return " ".join(text.replace("<", " ").split())


def _correct_digits(text: str, positions: list[int]) -> str:
    values = list(text)
    for index in positions:
        values[index] = values[index].translate(_DIGIT_CORRECTIONS)
    return "".join(values)


def _country(code: str) -> str | None:
    if code == "D<<":
        return "DE"
    try:
        return normalize_country(code.replace("<", ""))
    except ValueError:
        return None


def _evidence(regions: list[TextRegion]) -> list[dict]:
    return [{"text": region.text, "bbox": region.bbox, "source": "mrz", "confidence": region.confidence} for region in regions]


def parse_travel_mrz(regions: list[TextRegion]) -> TravelMRZResult | None:
    """Parse a supported exact-width MRZ without padding or guessed characters."""
    candidates: list[tuple[int, str, TextRegion]] = []
    for region in regions:
        for line in region.text.splitlines():
            text = re.sub(r"\s+", "", line.upper()).replace("«", "<").replace("‹", "<").replace(">", "<")
            if re.fullmatch(r"[A-Z0-9<]{30}|[A-Z0-9<]{36}|[A-Z0-9<]{44}", text):
                y = min((point[1] for point in region.bbox), default=0)
                candidates.append((y, text, region))
    candidates.sort(key=lambda candidate: candidate[0])
    parsed: list[TravelMRZResult] = []
    for index, (_, first, region) in enumerate(candidates):
        if len(first) == 30 and index + 2 < len(candidates):
            following = candidates[index:index + 3]
            if all(len(item[1]) == 30 for item in following):
                prefix, issuer = first[:2], first[2:5]
                document_type = "passport_card" if prefix == "IP" else "us_green_card" if issuer == "USA" and prefix in ("C1", "C2") else "us_ead" if issuer == "USA" and prefix == "IA" else None
                if document_type and re.fullmatch(r"[A-Z<]{30}", following[2][1]):
                    parsed.append(_parse_td1(document_type, [item[1] for item in following], [item[2] for item in following]))
        elif len(first) in (36, 44) and first.startswith("V") and index + 1 < len(candidates):
            second = candidates[index + 1]
            if len(second[1]) == len(first) and re.fullmatch(r"V[A-Z<][A-Z<]{3}[A-Z<]+", first):
                parsed.append(_parse_visa([first, second[1]], [region, second[2]]))
    if not parsed:
        return None
    # Multiple independent documents cannot safely be collapsed into one result.
    if len(parsed) > 1:
        parsed[0].errors.append("MULTIPLE_MRZ_DOCUMENTS")
    return parsed[0]


def _finish(document_type: str, lines: list[str], regions: list[TextRegion], fields: dict, checks: dict, name_line: str) -> TravelMRZResult:
    surname, _, given = name_line.partition("<<")
    fields.update({"surname": _name(surname) or None, "given_names": _name(given) or None, "country_code": lines[0][2:5], "mrz_raw": lines})
    errors = [f"MRZ_{key.upper()}_FAILED" for key, value in checks.items() if value is False]
    warnings = []
    for field_name in ("date_of_birth", "expiry_date"):
        if fields.get(field_name) is None:
            errors.append(f"MISSING_OR_INVALID_{field_name.upper()}")
    if fields.get("sex") not in ("M", "F", "X"):
        errors.append("INVALID_SEX")
    issuing_country = _country(fields["country_code"])
    if issuing_country is None:
        errors.append("UNKNOWN_ISSUING_COUNTRY")
    checks["mrz_checksums_valid"] = all(checks.values())
    checks["issuer_authenticated"] = False
    evidence = {name: _evidence(regions) for name, value in fields.items() if value is not None}
    return TravelMRZResult(document_type, issuing_country, fields, evidence, checks, errors, warnings)


def _parse_td1(document_type: str, lines: list[str], regions: list[TextRegion]) -> TravelMRZResult:
    first = _correct_digits(lines[0], [14])
    second = _correct_digits(lines[1], list(range(0, 7)) + list(range(8, 15)) + [29])
    surname_line = lines[2]
    number = first[5:14]
    number_check = first[14]
    fields: dict = {
        "document_number": number.rstrip("<") or None,
        "date_of_birth": _parse_mrz_date(second[:6]),
        "expiry_date": _parse_mrz_date(second[8:14], is_expiry=True),
        "sex": "X" if second[7] == "<" else second[7],
        "nationality": second[15:18].replace("<", "") or None,
    }
    # ICAO TD1 extended document numbers move their check digit into optional
    # data, immediately after the continuation and before a filler.
    if document_type == "passport_card" and number_check == "<":
        continuation = first[15:30].split("<", 1)[0]
        if len(continuation) >= 2 and continuation[-1].isdigit():
            number += continuation[:-1]
            number_check = continuation[-1]
            fields["document_number"] = number
    checks = {
        "document_number_checksum": verify_check_digit(number, number_check),
        "date_of_birth_checksum": verify_check_digit(second[:6], second[6]),
        "expiry_date_checksum": verify_check_digit(second[8:14], second[14]),
        "composite_checksum": verify_check_digit(first[5:30] + second[:7] + second[8:15] + second[18:29], second[29]),
    }
    if document_type in ("us_green_card", "us_ead"):
        fields.pop("document_number")
        fields.pop("nationality")
        fields["uscis_number"] = number.rstrip("<")
        fields["card_number"] = first[15:30].rstrip("<") or None
        # US profiles encode country of birth here, not citizenship.
        fields["country_of_birth"] = second[15:18].replace("<", "") or None
    result = _finish(document_type, [first, second, surname_line], regions, fields, checks, surname_line)
    if document_type in ("us_green_card", "us_ead"):
        if not re.fullmatch(r"[0-9]{9}", fields["uscis_number"] or ""):
            result.errors.append("INVALID_USCIS_NUMBER")
        if not re.fullmatch(r"[A-Z]{3}[0-9]{10}", fields["card_number"] or ""):
            result.errors.append("INVALID_CARD_NUMBER")
    return result


def _parse_visa(lines: list[str], regions: list[TextRegion]) -> TravelMRZResult:
    first, second = lines
    second = _correct_digits(second, [9] + list(range(13, 20)) + list(range(21, 28)))
    fields = {
        "document_number": second[:9].rstrip("<") or None,
        "date_of_birth": _parse_mrz_date(second[13:19]),
        "expiry_date": _parse_mrz_date(second[21:27], is_expiry=True),
        "nationality": second[10:13].replace("<", "") or None,
        "sex": "X" if second[20] == "<" else second[20],
        "mrz_format": "MRV_A" if len(first) == 44 else "MRV_B",
    }
    checks = {
        "document_number_checksum": verify_check_digit(second[:9], second[9]),
        "date_of_birth_checksum": verify_check_digit(second[13:19], second[19]),
        "expiry_date_checksum": verify_check_digit(second[21:27], second[27]),
    }
    return _finish("visa", [first, second], regions, fields, checks, first[5:])
