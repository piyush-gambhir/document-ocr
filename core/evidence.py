"""Conservative links from returned values to source text; never invent boxes."""
from __future__ import annotations

import re
from dataclasses import fields

from .ocr_engine import TextRegion


def camel(name: str) -> str:
    parts = name.split('_')
    return parts[0] + ''.join(p.title() for p in parts[1:])


def document_fields(result) -> dict:
    if result.document_fields is not None:
        return result.document_fields
    output = {}
    for attr in ('fields', 'back_page_fields', 'pan_fields', 'aadhaar_fields',
                 'driving_licence_fields', 'voter_id_fields', 'nrega_job_card_fields', 'npr_letter_fields'):
        block = getattr(result, attr, None)
        if block is not None:
            output.update({f.name: getattr(block, f.name) for f in fields(block)})
    return output


def _norm(value: str) -> str:
    return ''.join(c for c in value.casefold() if c.isalnum())


def field_evidence(values: dict, regions: list[TextRegion], *, source: str = 'ocr', mrz_raw=None) -> dict:
    evidence = {}
    mrz_fields = {'surname', 'given_names', 'full_name', 'passport_number', 'nationality',
                  'date_of_birth', 'sex', 'expiry_date', 'country_code'}
    for key, value in values.items():
        if not isinstance(value, (str, int)) or not str(value).strip():
            continue
        needle = _norm(str(value))
        hits = []
        for region in regions:
            is_mrz = bool(mrz_raw and region.text.replace(' ', '') in mrz_raw)
            date = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', str(value))
            match = needle in _norm(region.text)
            if date:
                y, m, d = date.groups()
                match |= any(x in _norm(region.text) for x in (d+m+y, m+d+y))
            if is_mrz and key in mrz_fields:
                match = True
            if match and (len(needle) > 1 or is_mrz):
                hits.append({'text': region.text, 'bbox': region.bbox,
                             'source': 'mrz' if is_mrz else source, 'confidence': region.confidence})
        if hits:
            evidence[key] = hits
    return evidence
