"""Compare fixed public-sample runs; refuse incompatible evaluation settings."""
import argparse
import json
from pathlib import Path


def compare_reports(before: dict, after: dict) -> dict:
    if before['scoringVersion'] != after['scoringVersion']:
        raise ValueError('scoring versions differ')
    a, b = before['provenance'], after['provenance']
    for key in ('scorerSha256', 'packages', 'modelSha256', 'kycLanguages', 'platform', 'python', 'cpuCount'):
        if key not in a or key not in b or a[key] != b[key]:
            raise ValueError(f'incompatible or missing provenance: {key}')
    if a['integrity']['manifestSha256'] != b['integrity']['manifestSha256']:
        raise ValueError('sample manifests differ')
    if not a.get('coreSha256') or not b.get('coreSha256'):
        raise ValueError('core fingerprints are required')
    improvements, regressions = [], []
    for mode, key in [('auto', 'cases'), ('hinted', 'hintedCases')]:
        old = {c['id']: c for c in before[key]}
        new = {c['id']: c for c in after[key]}
        if (len(old) != len(before[key]) or len(new) != len(after[key]) or old.keys() != new.keys()):
            raise ValueError('case IDs differ or are duplicated')
        for case_id, previous in old.items():
            current = new[case_id]
            if previous['fieldMatches'].keys() != current['fieldMatches'].keys():
                raise ValueError('field expectations differ')
            if (previous['mrzExact'] is None) != (current['mrzExact'] is None):
                raise ValueError('MRZ expectations differ')
            metrics = [('field:' + k, value, current['fieldMatches'][k])
                       for k, value in previous['fieldMatches'].items()]
            metrics += [('mrzExact', previous['mrzExact'], current['mrzExact']),
                        ('statusSuccess', previous['status'] == 'success', current['status'] == 'success'),
                        ('noRuntimeError', previous['runtimeError'] is None, current['runtimeError'] is None)]
            for metric, was, now in metrics:
                entry = {'mode': mode, 'id': case_id, 'metric': metric}
                if was is False and now is True:
                    improvements.append(entry)
                if was is True and now is False:
                    regressions.append(entry)
    return {'schemaVersion': 1, 'beforeCoreSha256': a['coreSha256'], 'afterCoreSha256': b['coreSha256'],
            'manifestSha256': a['integrity']['manifestSha256'], 'passed': not regressions,
            'improvedCaseIds': sorted({x['id'] for x in improvements}),
            'regressedCaseIds': sorted({x['id'] for x in regressions}),
            'improvements': improvements, 'regressions': regressions,
            'passportBefore': before['passport'], 'passportAfter': after['passport'],
            'latencyNote': 'Single-pass observations; latency is reported but not gated.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = compare_reports(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"Improved: {len(report['improvedCaseIds'])}; regressed: {len(report['regressedCaseIds'])}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
