"""Country-aware extraction for explicitly registered document profiles.

Machine-readable data and visual OCR remain separate evidence. Conflicting
values are surfaced instead of silently letting a confident source overwrite
another. These extraction checks do not authenticate a document or its holder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import pycountry

from .barcodes import BarcodeResult, parse_aamva
from .document_registry import DOCUMENT_PROFILES, normalize_country, validate_document_hint
from .ocr_engine import TextRegion
from .travel_mrz import parse_travel_mrz


@dataclass
class StructuredExtraction:
    document_type: str
    issuing_country: str | None = None
    issuing_region: str | None = None
    fields: dict = field(default_factory=dict)
    field_evidence: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    missing_required_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def complete(self) -> bool:
        return bool(self.fields) and not self.missing_required_fields and not self.errors


_US_STATES = {item.code.split("-")[1]: item.name.upper() for item in pycountry.subdivisions.get(country_code="US")}
_FIELD_LABEL = re.compile(
    r"^(?:\d+\s+)?(?:surname|family name|given names?|first name|middle name|date of birth|birth date|dob|"
    r"date of (?:issue|expiry)|exp(?:iry|iration)?(?: date)?|issue(?:d| date)?|sex|nationality|"
    r"uscis|card (?:number|expires)|category|country of birth|resident since|valid from|"
    r"class of admission|admit until|admission.*record number|passport number|"
    r"name(?: of entity/individual)?|business name|address|city|social security number|employer identification number)\b",
    re.I,
)


def _compact(value: str) -> str:
    return re.sub(r"[\s-]", "", value.upper())


def _us_date(value: str) -> str | None:
    value = value.strip().replace(".", "/")
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m%d%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _name(value: str) -> str | None:
    value = " ".join(value.strip(" :").split())
    if not 1 <= len(value) <= 100 or not re.search(r"[A-Za-z]", value):
        return None
    if re.search(r"\b(?:required|enter|instructions|certification|requester|taxpayer|identification|security)\b|shown on|line [0-9]", value, re.I):
        return None
    return value


def _pattern(pattern: str) -> Callable[[str], str | None]:
    return lambda value: _compact(value) if re.fullmatch(pattern, _compact(value)) else None


def _document_number(value: str) -> str | None:
    value = _compact(value)
    return value if re.fullmatch(r"[A-Z0-9]{4,25}", value) and re.search(r"[0-9]", value) else None


def _country_of_birth(value: str) -> str | None:
    try:
        return pycountry.countries.lookup(value.strip()).alpha_3
    except LookupError:
        return None


def _evidence(region: TextRegion, text: str | None = None) -> dict:
    return {"text": text if text is not None else region.text, "bbox": region.bbox, "source": "ocr", "confidence": region.confidence}


def _label_values(regions: list[TextRegion], labels: tuple[str, ...]):
    """Yield explicit inline values, then spatially adjacent non-label regions."""
    for label in labels:
        expression = re.compile(r"^\s*(?:" + label + r")(?![A-Za-z])\s*[:#]?\s*", re.I)
        for region in regions:
            match = expression.match(region.text)
            if not match:
                continue
            inline = region.text[match.end():].strip()
            if inline:
                yield inline, region
            if not region.bbox:
                continue
            left = min(point[0] for point in region.bbox)
            right = max(point[0] for point in region.bbox)
            top = min(point[1] for point in region.bbox)
            bottom = max(point[1] for point in region.bbox)
            height = max(bottom - top, 1)
            nearby = []
            for candidate in regions:
                if candidate is region or not candidate.bbox or _FIELD_LABEL.match(candidate.text):
                    continue
                c_left = min(point[0] for point in candidate.bbox)
                c_top = min(point[1] for point in candidate.bbox)
                c_bottom = max(point[1] for point in candidate.bbox)
                overlap = min(bottom, c_bottom) - max(top, c_top)
                if overlap >= height * 0.5 and 0 <= c_left - right < 450:
                    nearby.append((c_left - right, candidate))
                elif -5 <= c_top - bottom < max(90, height * 3) and abs(c_left - left) < 220:
                    # A blank field must not borrow the value belonging to the
                    # next labeled field underneath it (for example W-9 lines
                    # 1 and 2). A label in the same column closes this field.
                    crossed_label = any(
                        other is not region
                        and other.bbox
                        and _FIELD_LABEL.match(other.text)
                        and bottom - 5 <= min(point[1] for point in other.bbox) <= c_top
                        and abs(min(point[0] for point in other.bbox) - left) < 220
                        for other in regions
                    )
                    if crossed_label:
                        continue
                    nearby.append((500 + max(c_top - bottom, 0) + abs(c_left - left), candidate))
            for _, candidate in sorted(nearby, key=lambda item: item[0]):
                yield candidate.text, candidate


def _put(result: StructuredExtraction, key: str, value, evidence: dict | list[dict]) -> None:
    if value is None or value == "":
        return
    evidence = evidence if isinstance(evidence, list) else [evidence]
    result.field_evidence.setdefault(key, []).extend(evidence)
    previous = result.fields.get(key)
    if previous is not None and re.sub(r"\W", "", str(previous)).casefold() != re.sub(r"\W", "", str(value)).casefold():
        error = f"FIELD_MISMATCH_{key.upper()}"
        if error not in result.errors:
            result.errors.append(error)
        result.checks[f"{key}_agreement"] = False
        return
    result.fields[key] = value


def _visual(result: StructuredExtraction, regions: list[TextRegion], key: str, labels: tuple[str, ...], parser: Callable[[str], str | None] = _name) -> None:
    for raw, region in _label_values(regions, labels):
        value = parser(raw)
        if value is not None:
            _put(result, key, value, _evidence(region, raw))
            return


def _state(text: str) -> str | None:
    upper = text.upper()
    for code, name in _US_STATES.items():
        if re.search(r"\b" + re.escape(name) + r"\b", upper):
            return code
    return None


def _detect_text_type(regions: list[TextRegion]) -> tuple[str | None, str | None]:
    text = "\n".join(region.text.upper() for region in regions)
    state = _state(text)
    if state and re.search(r"\bDRIVER(?:'S|S)? LICENSE\b", text):
        return "us_driver_license", state
    if state and re.search(r"\b(?:IDENTIFICATION|IDENTITY) CARD\b", text):
        return "us_state_id", state
    american = bool(re.search(r"\bUSCIS\b|UNITED STATES", text))
    if american and "PERMANENT RESIDENT" in text:
        return "us_green_card", None
    if american and "EMPLOYMENT AUTHORIZATION" in text:
        return "us_ead", None
    if american and "PASSPORT CARD" in text:
        return "passport_card", None
    if re.search(r"\bI[ -]?94\b", text) and "CLASS OF ADMISSION" in text and re.search(r"ADMISSION.*RECORD NUMBER|CUSTOMS AND BORDER|HOMELAND SECURITY", text):
        return "us_i94", None
    if re.search(r"\bW[ -]?9\b", text) and "REQUEST FOR TAXPAYER IDENTIFICATION NUMBER" in text:
        return "us_w9", None
    return None, None


def _extract_aamva(barcodes: list[BarcodeResult]) -> StructuredExtraction | None:
    found: list[StructuredExtraction] = []
    for barcode in barcodes:
        if "PDF417" not in re.sub(r"[^A-Z0-9]", "", barcode.format.upper()):
            continue
        try:
            parsed = parse_aamva(barcode)
        except ValueError as error:
            # A corrupt payload cannot confidently identify DL versus ID.
            result = StructuredExtraction("us_driver_license", errors=[str(error)])
            result.checks.update({"barcode_decoded": True, "barcode_structure_valid": False})
            found.append(result)
            continue
        if parsed is None:
            continue
        raw = parsed.elements
        raw_country = raw.get("DCG")
        country = normalize_country(raw_country) if raw_country in ("US", "USA", "CA", "CAN") else None
        state = raw.get("DAJ")
        if country != "US" and not (raw_country is None and state in _US_STATES):
            continue
        result = StructuredExtraction(parsed.document_type, "US", state, errors=parsed.errors.copy())
        result.checks.update({"barcode_decoded": True, "barcode_structure_valid": not parsed.errors, "aamva_version": parsed.version, "aamva_jurisdiction_version": parsed.jurisdiction_version, "aamva_issuer_id": parsed.issuer_id, "issuer_authenticated": False, "signature_verified": False})
        evidence = {"text": barcode.text, "bbox": barcode.bbox, "source": "pdf417", "confidence": 1.0}
        keys = {"DAQ": "document_number", "DCS": "surname", "DAB": "surname", "DAC": "first_name", "DAD": "middle_names", "DAG": "address", "DAI": "city", "DAJ": "state", "DAK": "postal_code", "DCA": "license_class", "DCB": "restrictions", "DCD": "endorsements"}
        for element, key in keys.items():
            if parsed.document_type == "us_state_id" and element in ("DCA", "DCB", "DCD"):
                continue
            if raw.get(element):
                _put(result, key, raw[element], evidence)
        if raw.get("DAC"):
            _put(result, "given_names", " ".join(part for part in (raw["DAC"], raw.get("DAD")) if part), evidence)
        for element, key in (("DBB", "date_of_birth"), ("DBA", "expiry_date"), ("DBD", "issue_date")):
            if raw.get(element):
                value = _us_date(raw[element])
                if value is None:
                    result.errors.append(f"INVALID_{key.upper()}")
                else:
                    _put(result, key, value, evidence)
        if raw.get("DBC"):
            sex = {"1": "M", "2": "F", "9": "X"}.get(raw["DBC"])
            if sex is None:
                result.errors.append("INVALID_SEX")
            else:
                _put(result, "sex", sex, evidence)
        if state not in _US_STATES:
            result.errors.append("INVALID_ISSUING_REGION")
        for element in ("DDE", "DDF", "DDG"):
            if raw.get(element) == "T":
                result.warnings.append(f"AAMVA_NAME_TRUNCATED_{element}")
        found.append(result)
    if len(found) > 1:
        found[0].errors.append("MULTIPLE_AAMVA_DOCUMENTS")
    return found[0] if found else None


def _identity_visual(result: StructuredExtraction, regions: list[TextRegion]) -> None:
    _visual(result, regions, "surname", (r"surname", r"family name", r"last name", r"LN"))
    if result.document_type in ("us_driver_license", "us_state_id"):
        _visual(result, regions, "given_names", (r"given names?", r"FN"))
        _visual(result, regions, "first_name", (r"first name",))
        _visual(result, regions, "middle_names", (r"middle names?",))
    else:
        _visual(result, regions, "given_names", (r"given names?", r"first(?: \(given\))? name", r"FN"))
    _visual(result, regions, "date_of_birth", (r"date of birth", r"birth date(?: \([^)]*\))?", r"DOB"), _us_date)
    _visual(result, regions, "expiry_date", (r"card expires", r"date of expiry", r"expiration date", r"expiry date", r"EXP"), _us_date)
    _visual(result, regions, "sex", (r"sex",), lambda value: value.upper() if value.upper() in ("M", "F", "X") else None)


def _extract_visual(result: StructuredExtraction, regions: list[TextRegion]) -> None:
    kind = result.document_type
    if kind in ("us_driver_license", "us_state_id", "passport_card", "us_green_card", "us_ead", "visa"):
        _identity_visual(result, regions)
    if kind in ("us_driver_license", "us_state_id", "passport_card"):
        labels = (r"passport (?:card )?(?:number|no\.?)", r"card (?:number|no\.?)") if kind == "passport_card" else (r"(?:driver(?:'s)? license|license|licence|identification|id|dl)\s*(?:number|no\.?|#)", r"DL", r"ID")
        _visual(result, regions, "document_number", labels, _document_number)
        _visual(result, regions, "issue_date", (r"date of issue", r"issued", r"ISS"), _us_date)
        _visual(result, regions, "address", (r"address",), lambda value: value.strip() if re.search(r"[0-9]", value) else None)
    elif kind in ("us_green_card", "us_ead"):
        _visual(result, regions, "uscis_number", (r"USCIS\s*#?", r"A[ -]?(?:number|#)"), _pattern(r"[0-9]{9}"))
        _visual(result, regions, "card_number", (r"card\s*(?:#|number|no\.?)",), _pattern(r"[A-Z]{3}[0-9]{10}"))
        _visual(result, regions, "category", (r"category",), _pattern(r"[A-Z][0-9]{1,2}"))
        _visual(result, regions, "country_of_birth", (r"country of birth",), _country_of_birth)
        _visual(result, regions, "resident_since" if kind == "us_green_card" else "valid_from", (r"resident since",) if kind == "us_green_card" else (r"valid from",), _us_date)
    elif kind == "us_i94":
        _visual(result, regions, "i94_number", (r"admission\s*\(I[ -]?94\)\s*record number", r"I[ -]?94\s*(?:admission|record)?\s*(?:number|no\.?)", r"admission record number"), _pattern(r"[0-9]{9}[A-Z0-9][0-9]"))
        _visual(result, regions, "surname", (r"family name", r"surname"))
        _visual(result, regions, "given_names", (r"first(?: \(given\))? name", r"given name"))
        _visual(result, regions, "date_of_birth", (r"birth date(?: \([^)]*\))?", r"date of birth"), _us_date)
        _visual(result, regions, "class_of_admission", (r"class of admission",), _pattern(r"[A-Z][A-Z0-9]{0,4}"))
        _visual(result, regions, "admit_until", (r"admit until date(?: \([^)]*\))?", r"admit until"), lambda value: "D/S" if re.sub(r"\s", "", value.upper()) in ("D/S", "DS") else _us_date(value))
        _visual(result, regions, "admission_date", (r"most recent date of entry", r"date of entry(?: \([^)]*\))?", r"admission date"), _us_date)
        _visual(result, regions, "passport_number", (r"passport number",), _pattern(r"[A-Z0-9]{4,20}"))
        _visual(result, regions, "country_of_citizenship", (r"country of citizenship",), _name)
    elif kind == "us_w9":
        _visual(result, regions, "name", (r"1\s+name(?: of entity/individual)?(?:\s*\([^)]*\))?", r"name(?:\s*\([^)]*\))?"))
        _visual(result, regions, "business_name", (r"2\s+business name(?:/disregarded entity name)?(?:,?\s+if different from above)?", r"business name"))
        _visual(result, regions, "address", (r"5\s+address(?:\s*\([^)]*\))?", r"address"), lambda value: value.strip() if re.search(r"[0-9]", value) else None)
        _visual(result, regions, "city_state_postal_code", (r"6\s+city,?\s+state,?\s+and ZIP code", r"city,?\s+state,?\s+and ZIP code"), lambda value: value.strip() if re.search(r"\b[0-9]{5}(?:-[0-9]{4})?\b", value) else None)
        for labels, id_type in (((r"social security number", r"SSN"), "ssn"), ((r"employer identification number", r"EIN"), "ein")):
            for raw, region in _label_values(regions, labels):
                digits = _compact(raw)
                if re.fullmatch(r"[0-9]{9}", digits) and digits != "000000000":
                    _put(result, "taxpayer_id", digits, _evidence(region, raw))
                    _put(result, "taxpayer_id_type", id_type, _evidence(region, raw))
                    break


def _finish(result: StructuredExtraction) -> StructuredExtraction:
    profile = DOCUMENT_PROFILES[result.document_type]
    result.missing_required_fields = [name for name in profile.required_fields if not result.fields.get(name)]
    result.checks.setdefault("issuer_authenticated", False)
    result.checks["required_fields_present"] = not result.missing_required_fields
    birth, expiry = result.fields.get("date_of_birth"), result.fields.get("expiry_date")
    if birth and date.fromisoformat(birth) > date.today():
        result.errors.append("DATE_OF_BIRTH_IN_FUTURE")
    if birth and expiry and expiry <= birth:
        result.errors.append("EXPIRY_BEFORE_DATE_OF_BIRTH")
    if expiry:
        result.checks["printed_expiry_in_past"] = expiry < date.today().isoformat()
    scores = [item["confidence"] for items in result.field_evidence.values() for item in items]
    confidence = sum(scores) / len(scores) if scores else 0.0
    result.confidence = round(min(confidence, 0.49 if result.errors else 0.69 if result.missing_required_fields else 0.99), 3)
    result.errors = list(dict.fromkeys(result.errors))
    result.warnings = list(dict.fromkeys(["EXPERIMENTAL_DOCUMENT_PROFILE", *result.warnings]))
    return result


def extract_structured_document(
    regions: list[TextRegion],
    *,
    document_type: str | None = None,
    country: str | None = None,
    barcodes: list[BarcodeResult] | None = None,
) -> StructuredExtraction | None:
    """Extract a registered new profile; return None for legacy/unrecognized input."""
    document_type, country = validate_document_hint(document_type, country)
    if document_type and DOCUMENT_PROFILES[document_type].legacy:
        return None
    result = _extract_aamva(barcodes or [])
    mrz = parse_travel_mrz(regions)
    if result is not None and mrz is not None:
        result.errors.append("MULTIPLE_MACHINE_READABLE_DOCUMENTS")
    if result is None and mrz is not None:
        result = StructuredExtraction(mrz.document_type, mrz.issuing_country, fields=mrz.fields, field_evidence=mrz.field_evidence, checks=mrz.checks, errors=mrz.errors, warnings=mrz.warnings)
    text_type, state = _detect_text_type(regions)
    if result is None and text_type:
        result = StructuredExtraction(text_type, "US", state)
    if result is None:
        if document_type is None:
            return None
        result = StructuredExtraction(document_type, country, errors=["DOCUMENT_TYPE_NOT_CONFIRMED"])
        return _finish(result)
    if document_type is not None and result.document_type != document_type:
        result.errors.append("DOCUMENT_TYPE_MISMATCH")
    if country is not None and result.issuing_country is not None and result.issuing_country != country:
        result.errors.append("DOCUMENT_COUNTRY_MISMATCH")
    if text_type is not None and text_type != result.document_type:
        result.errors.append("DOCUMENT_TYPE_EVIDENCE_CONFLICT")
    _extract_visual(result, regions)
    if result.document_type in ("us_driver_license", "us_state_id") and not result.checks.get("barcode_decoded"):
        result.warnings.append("PDF417_NOT_DECODED")
    return _finish(result)
