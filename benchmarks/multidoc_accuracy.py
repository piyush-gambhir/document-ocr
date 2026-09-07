"""Repeat a fixed, small multi-document corpus and gate accuracy and warm latency.

Scoring is independent of production extractors. Reports contain match booleans,
counts and timings; image data, expected values and OCR responses stay local.
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
import random
import re
import statistics
import subprocess
import time

from benchmarks.public_accuracy import expected_fields
from benchmarks.public_data import inspect_samples, SAMPLE_ROOT, SAMPLES

EXPANSION = Path(__file__).with_name('public_expansion_samples.json')
POLICY = Path(__file__).with_name('multidoc_policy.json')


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile(case: dict) -> str:
    if case.get('profile'):
        return case['profile']
    if case['scope'] == 'TD3 passport':
        return 'passport'
    if case['dataset'] == 'idnet-part3':
        return 'us_driver_license'
    if case['dataset'] == 'cord-v2':
        return 'negative_control'
    if 'aadhaar' in case['id']:
        return 'aadhaar_observation'
    return 'other_observation'


def form_truth(truth: dict) -> dict:
    """Read linked publisher-renderer answers; never infer labels from OCR."""
    entities = json.loads(truth['funsd_json'])
    if isinstance(entities, dict):
        entities = entities['form']
    indexed = {item['id']: item for item in entities}
    answers = {}
    for question in entities:
        if question['label'] != 'question':
            continue
        linked = {b if a == question['id'] else a for a, b in question.get('linking', [])
                  if question['id'] in (a, b)}
        values = [indexed[i] for i in linked if indexed[i]['label'] == 'answer']
        values.sort(key=lambda item: (item['box'][1], item['box'][0]))
        answers[' '.join(question['text'].lower().split())] = [v['text'].strip() for v in values]

    def answer(prefix):
        matches = [values for label, values in answers.items() if label.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError('missing or ambiguous publisher form label')
        return ' '.join(v for v in matches[0] if v)

    fields = {'name': answer('1 name of entity/individual'),
              'businessName': answer('2 business name/disregarded entity name'),
              'address': answer('5 address'), 'cityStatePostalCode': answer('6 city, state, and zip code')}
    for label, kind in [('social security number', 'ssn'), ('employer identification number', 'ein')]:
        value = re.sub(r'[\s-]', '', answer(label))
        if value:
            if not re.fullmatch(r'[0-9]{9}', value) or 'taxpayerId' in fields:
                raise ValueError('ambiguous or invalid publisher TIN')
            fields.update(taxpayerId=value, taxpayerIdType=kind)
    if not fields['name'] or not fields.get('taxpayerId'):
        raise ValueError('incomplete publisher W-9 truth')
    return {key: value or None for key, value in fields.items()}


def expected(case: dict, root: Path) -> tuple[dict, list[str] | None]:
    kind = profile(case)
    if case['dataset'] in {'synthetic-contract', 'reviewed-specimen'}:
        truth = json.loads((root / case['truth']).read_text())
        return truth['fields'], truth.get('mrzRaw') if kind == 'passport' else None
    if kind in {'passport', 'us_driver_license'}:
        return expected_fields(case, root)
    if kind == 'us_w9':
        return form_truth(json.loads((root / case['truth']).read_text())), None
    if kind == 'passport_card':
        truth = json.loads((root / case['truth']).read_text())
        # Field mapping is reviewed against the publisher's source specimen.
        mapping = case['fieldMapping']
        fields = {target: truth[source]['value'] for target, source in mapping.items()}
        for key in ('dateOfBirth', 'expiryDate'):
            if key in fields:
                fields[key] = datetime.strptime(fields[key], case['dateFormat']).date().isoformat()
        return fields, None
    return {}, None


def score(case: dict, truth: tuple[dict, list[str] | None], actual: dict | None,
          elapsed: float, error: str | None) -> dict:
    fields, mrz = truth
    actual = actual or {}
    kind = profile(case)
    routed = actual.get('documentType') == kind
    values = actual.get(case.get('fieldBlock', 'fields' if kind == 'passport' else 'documentFields')) or {}
    matches, absent = {}, {}
    for key, value in fields.items():
        if value is None:
            absent[key] = values.get(key) in (None, "")
            continue
        found = values.get(key)
        if kind == 'passport' and key in ('dateOfBirth', 'expiryDate') and isinstance(found, str):
            try:
                found = datetime.strptime(found, '%Y-%m-%d').strftime('%y%m%d')
            except ValueError:
                found = None
        matches[key] = routed and found == value
    return {'fieldMatches': matches, 'absentFieldMatches': absent, 'mrzExact': (routed and actual.get('mrzRaw') == mrz) if mrz else None,
            'routingMatch': routed if fields else None, 'status': actual.get('status'),
            'documentType': actual.get('documentType'), 'runtimeError': error,
            'negativeRejected': (actual.get('status') in {'failure', 'unsupported_page'} and error is None) if kind == 'negative_control' else None,
            'elapsedMs': round(elapsed, 2)}


def percentile(values: list[float], percent: int) -> float | None:
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * percent + 99) // 100 - 1)] if ordered else None


def summarize(cases: list[dict]) -> dict:
    runs = [run for case in cases for run in case['runs']]
    fields = [value for run in runs for value in run['fieldMatches'].values()]
    times = [run['elapsedMs'] for run in runs]
    successes = [run['elapsedMs'] for run in runs if run['status'] == 'success']
    negatives = [run['negativeRejected'] for run in runs if run['negativeRejected'] is not None]
    scored = [run for run in runs if run['fieldMatches']]
    mrz = [run['mrzExact'] for run in runs if run['mrzExact'] is not None]
    unstable = sum(len({json.dumps({k: v for k, v in run.items() if k != 'elapsedMs'}, sort_keys=True)
                         for run in case['runs']}) > 1 for case in cases)
    return {'cases': len(cases), 'identityGroups': len({c['group'] for c in cases}), 'calls': len(runs),
            'scoredCases': sum(bool(c['runs'][0]['fieldMatches']) for c in cases),
            'fieldMatches': sum(fields), 'fieldExpectations': len(fields),
            'fieldAccuracy': sum(fields) / len(fields) if fields else None,
            'completeRecordAccuracy': sum(all(r['fieldMatches'].values()) for r in scored) / len(scored) if scored else None,
            'acceptedPositiveAccuracy': sum(r['status'] == 'success' for r in scored) / len(scored) if scored else None,
            'spuriousFields': sum(not value for r in runs for value in r['absentFieldMatches'].values()),
            'mrzMatches': sum(mrz), 'mrzExpectations': len(mrz),
            'negativeRejections': sum(negatives), 'negativeExpectations': len(negatives),
            'statuses': dict(Counter(r['status'] or 'exception' for r in runs)),
            'runtimeErrors': sum(r['runtimeError'] is not None for r in runs), 'unstableCases': unstable,
            'medianMs': statistics.median(times) if times else None, 'p95Ms': percentile(times, 95),
            'successfulMedianMs': statistics.median(successes) if successes else None,
            'successfulP95Ms': percentile(successes, 95)}


def gate(report: dict, policy: dict, baseline: dict | None = None) -> dict:
    failures = []
    if report['repeats'] < policy['minimumRepeats']:
        failures.append('INSUFFICIENT_REPEATS')
    for kind, thresholds in policy['profiles'].items():
        summary = report['profiles'].get(kind)
        if not summary or summary['scoredCases'] < thresholds['minimumCases']:
            failures.append(kind + ':INSUFFICIENT_CASES')
            continue
        for metric in ('fieldAccuracy', 'completeRecordAccuracy', 'acceptedPositiveAccuracy'):
            if summary[metric] is None or summary[metric] < thresholds[metric]:
                failures.append(kind + ':' + metric)
    operational_failures = [f for f in failures if 'INSUFFICIENT_' in f]
    if report.get('coldStartError'):
        failures.append('COLD_START_ERROR')
        operational_failures.append('COLD_START_ERROR')
    if report.get('sourceUnchanged') is False:
        failures.append('SOURCE_CHANGED_DURING_RUN')
        operational_failures.append('SOURCE_CHANGED_DURING_RUN')
    for kind, summary in report['profiles'].items():
        if summary['spuriousFields']:
            failures.append(kind + ':SPURIOUS_FIELDS')
            operational_failures.append(kind + ':SPURIOUS_FIELDS')
        if summary['runtimeErrors'] or summary['unstableCases']:
            failures.append(kind + ':ERROR_OR_INSTABILITY')
            operational_failures.append(kind + ':ERROR_OR_INSTABILITY')
        if summary['negativeRejections'] != summary['negativeExpectations']:
            failures.append(kind + ':FALSE_ACCEPTANCE')
            operational_failures.append(kind + ':FALSE_ACCEPTANCE')
        if summary['p95Ms'] > policy['maxWarmP95Ms']:
            failures.append(kind + ':LATENCY_BUDGET')
    regressions, latency_comparisons = [], {}
    if baseline:
        if baseline.get('sourceUnchanged') is False:
            raise ValueError('incompatible baseline: source changed during measurement')
        for key in ('schemaVersion', 'repeats', 'seed', 'policySha256'):
            if baseline[key] != report[key]:
                raise ValueError('incompatible benchmark: ' + key)
        for key in ('manifestSha256', 'scorerSha256', 'packages', 'modelSha256', 'platform', 'python', 'cpuCount', 'kycLanguages'):
            if baseline['provenance'][key] != report['provenance'][key]:
                raise ValueError('incompatible benchmark provenance: ' + key)
        old = {case['id']: case for case in baseline['cases']}
        if len(old) != len(baseline['cases']) or len(report['cases']) != len(old) or set(old) != {c['id'] for c in report['cases']}:
            raise ValueError('incompatible case IDs')
        for case in report['cases']:
            previous = old[case['id']]
            if len(previous['runs']) != len(case['runs']):
                raise ValueError('incompatible case repeat count')
            for before, after in zip(previous['runs'], case['runs']):
                if (before['fieldMatches'].keys() != after['fieldMatches'].keys()
                        or before['absentFieldMatches'].keys() != after['absentFieldMatches'].keys()):
                    raise ValueError('incompatible field denominators')
                pairs = [(key, val, after['fieldMatches'][key]) for key, val in before['fieldMatches'].items()]
                pairs += [('absent:' + key, val, after['absentFieldMatches'][key]) for key, val in before['absentFieldMatches'].items()]
                pairs += [(key, before[key], after[key]) for key in ('mrzExact', 'routingMatch', 'negativeRejected')]
                pairs.append(('statusSuccess', before['status'] == 'success', after['status'] == 'success'))
                for metric, was, now in pairs:
                    if (was is None) != (now is None):
                        raise ValueError('incompatible metric denominators')
                    if was is True and now is False:
                        regressions.append({'id': case['id'], 'metric': metric})
        # Compare successful extraction and unchanged rejection workloads.
        # Newly readable documents cannot be compared with pre-OCR rejection.
        # Rejecting unsupported input is also work with a latency budget.
        def comparable(a, b):
            if a['runtimeError'] or b['runtimeError']:
                return False
            if a['status'] == b['status'] == 'success':
                return True
            return {k: v for k, v in a.items() if k != 'elapsedMs'} == {
                k: v for k, v in b.items() if k != 'elapsedMs'}

        for kind in report['profiles']:
            pairs = [(a['elapsedMs'], b['elapsedMs']) for c in report['cases'] if c['profile'] == kind
                     for a, b in zip(old[c['id']]['runs'], c['runs'])
                     if comparable(a, b)]
            if len(pairs) < 5:
                latency_comparisons[kind] = {'comparableCalls': len(pairs), 'measured': False}
                continue
            before_times, after_times = zip(*pairs)
            latency_comparisons[kind] = {'comparableCalls': len(pairs), 'measured': True}
            for metric, function in [('medianMs', statistics.median), ('p95Ms', lambda xs: percentile(xs, 95))]:
                old_value, new_value = function(before_times), function(after_times)
                latency_comparisons[kind][metric] = {'before': old_value, 'after': new_value}
                allowance = max(policy['latencyNoiseFloorMs'], old_value * policy['maxLatencyIncreaseFraction'])
                if new_value > old_value + allowance:
                    failures.append(kind + ':REGRESSED_' + metric)
                    operational_failures.append(kind + ':REGRESSED_' + metric)
    if regressions:
        failures.append('ACCURACY_REGRESSION')
    return {'passed': not failures, 'failures': sorted(set(failures)),
            'regressionPassed': not regressions and not operational_failures,
            'latencyComparison': latency_comparisons,
            'regressions': [dict(entry) for entry in sorted({tuple(sorted(r.items())) for r in regressions})]}


def run(manifests: list[Path], root: Path, repeats: int, seed: int, raw_path: Path) -> dict:
    from core.pipeline import scan
    import core
    import rapidocr

    cases, integrity = [], []
    for path in manifests:
        manifest = json.loads(path.read_text())
        integrity.append(inspect_samples(manifest, root))
        cases.extend(manifest['cases'])
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('duplicate case IDs across manifests')
    truths = {c['id']: expected(c, root) for c in cases}
    model_dir = Path(rapidocr.__file__).parent / 'models'
    provenance = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  'coreSha256': hashlib.sha256(b''.join(p.name.encode() + b'\0' + p.read_bytes()
                         for p in sorted(Path(core.__file__).parent.glob('*.py')))).hexdigest(),
                  'scorerSha256': hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('multidoc_accuracy.py', 'public_accuracy.py', 'public_data.py'))).hexdigest(),
                  'manifestSha256': [i['manifestSha256'] for i in integrity], 'integrity': integrity,
                  'platform': platform.platform(), 'python': platform.python_version(), 'cpuCount': os.cpu_count(),
                  'kycLanguages': os.getenv('DOCUMENT_OCR_KYC_LANGS', ''),
                  'packages': {k: importlib.metadata.version(k) for k in ['rapidocr', 'onnxruntime', 'numpy', 'opencv-python', 'pillow']}}
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_file = raw_path.open('w')

    def measure(case, iteration):
        start = time.perf_counter()
        try:
            actual = scan(str(root / case['image']), **case.get('options', {})).to_dict()
            error = None
        except Exception as exc:
            actual, error = None, type(exc).__name__
        elapsed = (time.perf_counter() - start) * 1000
        raw_file.write(json.dumps({'id': case['id'], 'iteration': iteration, 'actual': actual, 'error': error}) + '\n')
        raw_file.flush()
        return score(case, truths[case['id']], actual, elapsed, error)

    results = {c['id']: {'id': c['id'], 'group': c['group'], 'profile': profile(c),
                         'capture': c.get('capture', c['id'].rsplit('/', 1)[-1]),
                         'split': c.get('split', 'original_smoke'), 'runs': []} for c in cases}
    try:
        cold = measure(cases[0], -1)
        if cold['runtimeError'] == 'OCRModelInitError':
            raise RuntimeError('OCR model initialization failed; refusing to retry setup for every case')
        # Warm every family before timing. Cold model startup is reported separately.
        seen = set()
        for case in cases:
            if profile(case) not in seen:
                measure(case, -1)
                seen.add(profile(case))
        for iteration in range(repeats):
            order = list(cases)
            random.Random(seed + iteration).shuffle(order)
            for index, case in enumerate(order):
                results[case['id']]['runs'].append(measure(case, iteration))
                if (index + 1) % 10 == 0:
                    print(f'Repeat {iteration + 1}/{repeats}: {index + 1}/{len(cases)}', flush=True)
    finally:
        raw_file.close()
    provenance['modelSha256'] = {p.name: fingerprint(p) for p in sorted(model_dir.glob('*.onnx'))}
    records = list(results.values())
    source_unchanged = provenance['coreSha256'] == hashlib.sha256(b''.join(
        p.name.encode() + b'\0' + p.read_bytes()
        for p in sorted(Path(core.__file__).parent.glob('*.py')))).hexdigest()
    return {'schemaVersion': 1, 'repeats': repeats, 'seed': seed, 'provenance': provenance,
            'sourceUnchanged': source_unchanged,
            'coldStartMs': cold['elapsedMs'], 'coldStartError': cold['runtimeError'],
            'overall': summarize(records),
            'profiles': {kind: summarize([c for c in records if c['profile'] == kind]) for kind in sorted(seen)},
            'slices': {split: summarize([c for c in records if c['split'] == split]) for split in sorted({c['split'] for c in records})},
            'cases': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, action='append')
    parser.add_argument('--root', type=Path, default=SAMPLE_ROOT)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--seed', type=int, default=20260908)
    parser.add_argument('--policy', type=Path, default=POLICY)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--regressions-only', action='store_true', help='Require a matched baseline; report unmet absolute targets but gate only regressions and operational errors.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--raw-output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('repeats must be between 1 and 10')
    if args.regressions_only and not args.baseline:
        parser.error('--regressions-only requires --baseline')
    raw_output = args.raw_output or Path('benchmark-data/multidoc') / (args.output.stem + '-raw.jsonl')
    report = run(args.manifest or [SAMPLES, EXPANSION], args.root, args.repeats, args.seed, raw_output)
    report['policySha256'] = fingerprint(args.policy)
    report['gates'] = gate(report, json.loads(args.policy.read_text()),
                           json.loads(args.baseline.read_text()) if args.baseline else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'overall': report['overall'], 'profiles': report['profiles'], 'gates': report['gates']}, indent=2))
    return 0 if report['gates']['regressionPassed' if args.regressions_only else 'passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
