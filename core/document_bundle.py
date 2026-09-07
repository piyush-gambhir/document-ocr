"""Batch independent documents, or reconcile explicitly grouped document pages."""
from __future__ import annotations

import time

from .document_input import MAX_PAGES, input_bytes, pdf_pages
from .document_registry import validate_document_hint
from .pipeline import scan, _scan_page, DocumentScanResult
from .preprocessor import PreprocessResult, ImageQualityError


def scan_batch(images, **options) -> dict:
    if not 1 <= len(images) <= MAX_PAGES:
        raise ValueError('INVALID_BATCH_SIZE')
    results = [scan(data, **options).to_dict() for data in images]
    successes = sum(r['status'] == 'success' for r in results)
    return {'status': 'success' if successes == len(results) else 'partial' if successes else 'failure',
            'results': results, 'errors': []}


def scan_document(images, **options) -> dict:
    """Merge same-family pages only; disagreements require human review.

    Independent records belong in scan_batch. A conflicting field is omitted
    from the merged fields, with all page values retained in conflicts/results.
    """
    if not 1 <= len(images) <= MAX_PAGES:
        raise ValueError('INVALID_BATCH_SIZE')
    document_type, country = validate_document_hint(options.get('document_type'), options.get('country'))
    results = []
    for data in images:
        data = input_bytes(data)
        if data.startswith(b'%PDF-'):
            try:
                pages = pdf_pages(data)
                if len(results) + len(pages) > MAX_PAGES:
                    raise ValueError('TOO_MANY_PAGES')
                for page in pages:
                    result = _scan_page(PreprocessResult(page.image), time.monotonic(), document_type,
                                        country, True, native=page.regions)
                    results.append(result.to_dict())
            except ImageQualityError as exc:
                results.append(DocumentScanResult('failure', 'unknown', 'unknown', 0, errors=[str(exc)]).to_dict())
        else:
            results.append(scan(data, document_type=document_type, country=country, include_evidence=True).to_dict())
        if len(results) > MAX_PAGES:
            raise ValueError('TOO_MANY_PAGES')
    return reconcile_pages(results, include_evidence=options.get('include_evidence', False))


def reconcile_pages(results: list[dict], *, include_evidence: bool = True) -> dict:
    values = {}
    for page, result in enumerate(results, 1):
        for key, value in result.get('documentFields', {}).items():
            if value is not None and value != '' and value != []:
                values.setdefault(key, []).append({'page': page, 'value': value})
        if result['documentType'] != 'unknown':
            values.setdefault('documentType', []).append({'page': page, 'value': result['documentType']})
        if result.get('issuingCountry'):
            values.setdefault('issuingCountry', []).append({'page': page, 'value': result['issuingCountry']})
        for items in result.get('fieldEvidence', {}).values():
            for item in items:
                item['page'] = page
        if not include_evidence:
            result.pop('fieldEvidence', None)
            result.pop('imageSize', None)
    merged, conflicts = {}, []
    for key, entries in values.items():
        first = entries[0]['value']
        # Only whitespace/case differences can be merged without a domain rule.
        def canonical(value):
            return ' '.join(value.upper().split()) if isinstance(value, str) else value
        if any(canonical(e['value']) != canonical(first) for e in entries):
            conflicts.append({'field': key, 'values': entries})
        elif key not in {'documentType', 'issuingCountry'}:
            merged[key] = first
    if any(conflict['field'] == 'documentType' for conflict in conflicts):
        merged = {}
    errors = ['CONFLICTING_DOCUMENT_PAGES'] if conflicts else []
    successful = sum(r['status'] == 'success' for r in results)
    status = 'failure' if conflicts else ('success' if successful == len(results) else 'partial' if successful else 'failure')
    return {'status': status, 'results': results, 'documentFields': merged, 'conflicts': conflicts, 'errors': errors}
