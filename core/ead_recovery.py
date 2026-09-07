"""Read an incomplete EAD once without contrast enhancement; expose conflicts."""
from __future__ import annotations

import re

import numpy as np

from .card_recovery import _read_box
from .structured_documents import StructuredExtraction, _finish, extract_structured_document


def recover_ead_fields(unenhanced_image, initial: StructuredExtraction, ocr, recognize_line) -> StructuredExtraction | None:
    if (unenhanced_image is None or initial.document_type != 'us_ead'
            or initial.issuing_country != 'US' or initial.complete or len(initial.fields) < 3
            or 'DOCUMENT_TYPE_NOT_CONFIRMED' in initial.errors):
        return None
    regions = ocr(unenhanced_image)
    fresh = extract_structured_document(regions)
    if fresh is None or fresh.document_type != 'us_ead' or fresh.issuing_country != 'US':
        return None
    if 'expiry_date' in fresh.missing_required_fields:
        # An observed truncated label locates the pixels; only a fresh read of
        # the complete label can associate a date with expiry.
        anchor = next((row for row in regions if row.confidence >= .9 and len(row.bbox) == 4
                       and re.fullmatch(r'card\s+expir(?:e|es)?[.:]?', row.text.strip(), re.I)), None)
        if anchor:
            points = np.asarray(anchor.bbox, np.float32)
            if np.isfinite(points).all():
                tl, tr, br, bl = points
                along = tr - tl
                width, height = int(np.linalg.norm(along) * 1.2), int(np.linalg.norm(bl - tl))
                read = _read_box(unenhanced_image, [tl - .1 * along, tr + .1 * along,
                                                    br + .1 * along, bl - .1 * along], width, height, recognize_line)
                if (len(read) == 1 and read[0].confidence >= .9
                        and re.fullmatch(r'card\s+expires[.:]?', read[0].text.strip(), re.I)):
                    regions = regions + read
                    fresh = extract_structured_document(regions)
    if (fresh is None or fresh.errors or set(initial.fields) - set(fresh.fields)
            or (len(fresh.fields) <= len(initial.fields)
                and len(fresh.missing_required_fields) >= len(initial.missing_required_fields))):
        return None
    added = fresh.fields.keys() - initial.fields.keys()
    if any(not fresh.field_evidence.get(key)
           or min(item['confidence'] for item in fresh.field_evidence[key]) < .9 for key in added):
        return None
    conflicts = [key for key, value in initial.fields.items()
                 if value not in (None, '') and fresh.fields[key] != value]
    for key in conflicts:
        fresh.field_evidence.setdefault(key, []).extend(initial.field_evidence.get(key, []))
        fresh.errors.append('OCR_VIEW_CONFLICT_' + key.upper())
    fresh.errors.extend(initial.errors)
    fresh.checks['ocr_view_agreement'] = not conflicts
    fresh.warnings.append('UNENHANCED_OCR_RECOVERY')
    return _finish(fresh)
