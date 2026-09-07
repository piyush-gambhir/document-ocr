"""Evaluate the frozen public smoke sample against the real local scan pipeline.

No training, generated ground truth, quality-gate bypass, or hosted API calls.
Raw responses remain in the ignored data root; public reports contain scores only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time

from benchmarks.public_data import SAMPLES, SAMPLE_ROOT, inspect_samples

SCORING_VERSION = 1


def expected_fields(case: dict, root: Path) -> tuple[dict, list[str] | None]:
    """Read publisher truth independently of the production OCR/MRZ parser."""
    truth = json.loads((root / case['truth']).read_text())
    if case['dataset'] == 'midv-2020' and case['scope'] == 'TD3 passport':
        entry = next(v for v in truth['_via_img_metadata'].values()
                     if v['filename'] == case['truthSelector']['viaFilename'])
        fields = {r['region_attributes'].get('field_name'): r['region_attributes'].get('value')
                  for r in entry['regions']}
        first, second = fields['mrz_line0'], fields['mrz_line1']
        if len(first) != 44 or len(second) != 44 or not first.startswith('P'):
            raise ValueError('source is not an annotated TD3 pair')
        surname, given = first[5:].split('<<', 1)
        clean = lambda text: ' '.join(text.replace('<', ' ').split())
        # MRZ dates encode YYMMDD only. Century inference is deliberately unscored.
        return {'surname': clean(surname), 'givenNames': clean(given),
                'passportNumber': second[:9].replace('<', ''), 'countryCode': first[2:5],
                'nationality': second[10:13], 'dateOfBirth': second[13:19],
                'sex': second[20], 'expiryDate': second[21:27]}, [first, second]
    if case['dataset'] == 'idnet-part3':
        return {'documentNumber': truth['license_number'],
                **{target: datetime.strptime(truth[source], '%m/%d/%Y').date().isoformat()
                   for target, source in [('dateOfBirth', 'birthday'), ('expiryDate', 'expire_date'),
                                           ('issueDate', 'issue_date')]}}, None
    return {}, None


def score_case(case: dict, expected: dict, mrz: list[str] | None, measured: dict) -> dict:
    actual = measured.get('actual') or {}
    passport = mrz is not None
    expected_type = 'passport' if passport else 'us_driver_license'
    routed = actual.get('documentType') == expected_type
    values = actual.get('fields' if passport else 'documentFields') or {}
    matches = {}
    for key, value in expected.items():
        found = values.get(key)
        if passport and key in ('dateOfBirth', 'expiryDate') and isinstance(found, str):
            try:
                found = datetime.strptime(found, '%Y-%m-%d').strftime('%y%m%d')
            except ValueError:
                found = None
        matches[key] = routed and found == value
    errors = [e if isinstance(e, str) and re.fullmatch('[A-Z][A-Z0-9_]*', e) else 'OTHER'
              for e in actual.get('errors', [])]
    return {'id': case['id'], 'group': case['group'], 'dataset': case['dataset'],
            'capture': case.get('capture', case['id'].rsplit('/', 1)[-1]),
            'status': actual.get('status'), 'documentType': actual.get('documentType'),
            'errors': errors, 'runtimeError': measured.get('errorType'),
            'elapsedMs': round(measured['elapsedMs'], 2),
            'scored': bool(expected), 'routingMatch': routed if expected else None,
            'fieldMatches': matches,
            'allScoredFieldsExact': all(matches.values()) if matches else None,
            'mrzExact': (routed and actual.get('mrzRaw') == mrz) if mrz else None}


def aggregate(cases: list[dict]) -> dict:
    fields = [(key, matched) for case in cases for key, matched in case['fieldMatches'].items()]
    per_field = {}
    for key, matched in fields:
        value = per_field.setdefault(key, {'matches': 0, 'total': 0})
        value['matches'] += int(matched)
        value['total'] += 1
    mrz = [c['mrzExact'] for c in cases if c['mrzExact'] is not None]
    times = sorted(c['elapsedMs'] for c in cases)
    return {'cases': len(cases), 'identityGroups': len({c['group'] for c in cases}),
            'statuses': dict(Counter(c['status'] or 'exception' for c in cases)),
            'runtimeErrors': sum(c['runtimeError'] is not None for c in cases),
            'fieldMatches': sum(m for _, m in fields), 'fieldExpectations': len(fields),
            'fieldAccuracy': sum(m for _, m in fields) / len(fields) if fields else None,
            'allScoredFieldsExact': sum(c['allScoredFieldsExact'] is True for c in cases),
            'scoredCases': sum(c['scored'] for c in cases), 'perField': per_field,
            'mrzMatches': sum(mrz), 'mrzExpectations': len(mrz),
            'medianMs': statistics.median(times) if times else None,
            'p95Ms': times[max(0, (95 * len(times) + 99) // 100 - 1)] if times else None}


def evaluate(manifest: dict, root: Path, raw: dict) -> dict:
    expected_ids = [c['id'] for c in manifest['cases']]
    if [c['id'] for c in raw['cases']] != expected_ids:
        raise ValueError('measured case IDs/order differ from the frozen manifest')
    scores, hinted = [], []
    for case, measured in zip(manifest['cases'], raw['cases']):
        expected, mrz = expected_fields(case, root)
        scores.append(score_case(case, expected, mrz, measured['auto']))
        if 'hinted' in measured:
            hinted.append(score_case(case, expected, mrz, measured['hinted']))
    passports = [c for c in scores if c['mrzExact'] is not None]
    return {'scoringVersion': SCORING_VERSION, 'measurement': 'local core.pipeline.scan; warm single pass',
            'limitations': ['Small non-random smoke sample, not population accuracy.',
                           'MRZ-derived date scores test YYMMDD, not inferred century.',
                           'Other families have routing/status observations only, not field accuracy.',
                           'Latency includes quality rejections; no HTTP, cloud or concurrency overhead.',
                           'Single pass is not a stable performance benchmark or an improvement claim.'],
            'provenance': {k: v for k, v in raw.items() if k != 'cases'},
            'overall': aggregate(scores), 'passport': aggregate(passports),
            'passportByCapture': {capture: aggregate([c for c in passports if c['capture'] == capture])
                                  for capture in sorted({c['capture'] for c in passports})},
            'usAuto': aggregate([c for c in scores if c['dataset'] == 'idnet-part3']),
            'usHinted': aggregate(hinted), 'cases': scores, 'hintedCases': hinted}


def run(root: Path, manifest: dict, raw_path: Path) -> dict:
    from core.pipeline import scan
    import rapidocr

    integrity = inspect_samples(manifest, root)
    model_dir = Path(rapidocr.__file__).parent / 'models'
    raw = {'integrity': integrity,
           'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
           'scorerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'platform': platform.platform(), 'python': platform.python_version(),
           'cpuCount': os.cpu_count(), 'kycLanguages': os.getenv('DOCUMENT_OCR_KYC_LANGS', ''),
           'packages': {k: importlib.metadata.version(k) for k in
                        ['rapidocr', 'onnxruntime', 'numpy', 'opencv-python', 'pillow']}, 'cases': []}
    def measure(case, **hints):
        start = time.perf_counter()
        try:
            actual = scan(str(root / case['image']), **hints).to_dict()
            result = {'actual': actual}
        except Exception as error:
            result = {'actual': None, 'errorType': type(error).__name__}
        result['elapsedMs'] = (time.perf_counter() - start) * 1000
        return result
    warm = measure(manifest['cases'][0])
    raw['warmupMs'] = warm['elapsedMs']
    raw['warmupError'] = warm.get('errorType')
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    for case in manifest['cases']:
        measured = {'id': case['id'], 'auto': measure(case)}
        if case['dataset'] == 'idnet-part3':
            measured['hinted'] = measure(case, document_type='us_driver_license', country='US')
        raw['cases'].append(measured)
        raw_path.write_text(json.dumps(raw, indent=2) + '\n')
        print(f"Measured {len(raw['cases'])}/{len(manifest['cases'])}: {case['id']}", flush=True)
    raw['modelSha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(model_dir.glob('*.onnx'))}
    raw_path.write_text(json.dumps(raw, indent=2) + '\n')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SAMPLE_ROOT)
    parser.add_argument('--output', type=Path, default=Path('benchmark-data/public-run/report.json'))
    args = parser.parse_args()
    manifest = json.loads(SAMPLES.read_text())
    raw = run(args.root, manifest, Path('benchmark-data/public-run/raw.json'))
    report = evaluate(manifest, args.root, raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['overall', 'passport', 'usAuto']}, indent=2))


if __name__ == '__main__':
    main()
