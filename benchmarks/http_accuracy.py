"""Bounded, real HTTP OCR evaluation against checksum-pinned local samples.

Starts an authenticated loopback uvicorn process. Client concurrency measures
queueing through the production server, which currently runs one OCR at a time.
Reports contain scores and timing only; uploaded bytes and response fields are
never written. This is a closed-loop capacity smoke test, not a production SLA.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import platform
import random
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import time

import httpx
from cryptography.fernet import Fernet
from PIL import Image

from benchmarks.multidoc_accuracy import EXPANSION, expected, fingerprint, percentile, profile, score, summarize
from benchmarks.public_data import SAMPLES, SAMPLE_ROOT, inspect_samples

REPO = Path(__file__).resolve().parents[1]
SERVER_BOOTSTRAP = '''import json, os, sys
from pathlib import Path
import uvicorn
from deploy.docker import server
Path(sys.argv[2]).write_text(json.dumps({
    "processes": 1,
    "ocrSlots": server._ocr_semaphore._value,
    "scanTimeoutSeconds": server.SCAN_TIMEOUT_SECONDS,
    "maxUploadBytes": server.MAX_UPLOAD_SIZE,
    "nativeThreadEnvironment": {key: os.getenv(key) for key in
        ("OMP_NUM_THREADS", "OMP_WAIT_POLICY", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
}))
uvicorn.run(server.app, fd=int(sys.argv[1]), access_log=False, log_level="warning")
'''


def semantic_response(value):
    """Ignore only server timing; preserve fields, errors, evidence and routing."""
    if isinstance(value, dict):
        return {key: semantic_response(item) for key, item in value.items() if key != 'processingMs'}
    if isinstance(value, list):
        return [semantic_response(item) for item in value]
    return value


def decode_scan(response: httpx.Response) -> tuple[dict | None, str | None]:
    try:
        actual = response.json()
    except ValueError:
        return None, 'INVALID_JSON'
    if response.status_code not in (200, 422):
        return None, 'HTTP_' + str(response.status_code)
    if (not isinstance(actual, dict) or actual.get('status') not in {'success', 'failure', 'unsupported_page'}
            or not isinstance(actual.get('documentType'), str)
            or not isinstance(actual.get('processingMs'), (int, float))
            or isinstance(actual.get('processingMs'), bool) or not math.isfinite(actual['processingMs'])
            or actual['processingMs'] < 0):
        return None, 'INVALID_SCAN_RESPONSE'
    if (response.status_code == 422) != (actual['status'] == 'failure'):
        return None, 'HTTP_STATUS_MISMATCH'
    blocks = ('fields', 'documentFields', 'backPageFields', 'panFields', 'aadhaarFields',
              'drivingLicenceFields', 'voterIdFields', 'nregaJobCardFields', 'nprLetterFields')
    if any(actual.get(key) is not None and not isinstance(actual[key], dict) for key in blocks):
        return None, 'INVALID_SCAN_RESPONSE'
    return actual, None


def select_cases(cases: list[dict], limit: int | None) -> list[dict]:
    """Deterministic round-robin preserves every profile before extra captures."""
    if limit is None or limit >= len(cases):
        return cases
    kinds = sorted({profile(case) for case in cases})
    if limit < len(kinds):
        raise ValueError('case limit must cover every profile: ' + str(len(kinds)))
    groups = {kind: [c for c in cases if profile(c) == kind] for kind in kinds}
    output = []
    while len(output) < limit:
        for kind in kinds:
            if groups[kind] and len(output) < limit:
                output.append(groups[kind].pop(0))
    return output


async def wait_ready(client: httpx.AsyncClient, process, timeout: float) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError('HTTP_SERVER_EXITED: see local server log')
        try:
            response = await client.get('/ready', timeout=min(1, max(.01, deadline - time.perf_counter())))
            payload = response.json()
            if response.status_code == 200 and isinstance(payload, dict) and payload.get('status') == 'ready':
                return
            if isinstance(payload, dict) and payload.get('status') == 'model_init_failed':
                raise RuntimeError('MODEL_INIT_FAILED: see local server log')
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(.1)
    raise TimeoutError('HTTP_SERVER_STARTUP_TIMEOUT')


@asynccontextmanager
async def local_server(source: Path, log: Path, startup_timeout: float, request_timeout: float):
    token = secrets.token_urlsafe(24)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log.open('w') as output, tempfile.TemporaryDirectory(prefix='ocr-http-jobs-') as jobs:
        environment = {**os.environ, 'PYTHONPATH': str(source), 'API_TOKEN': token,
                       'DOCUMENT_OCR_JOBS_DIR': jobs,
                       'DOCUMENT_OCR_JOB_KEY': Fernet.generate_key().decode(),
                       'DOCUMENT_OCR_JOB_RETENTION_SECONDS': '60'}
        # The benchmark owns an isolated local queue and never sends webhooks.
        environment.pop('DOCUMENT_OCR_WEBHOOK_URL', None)
        environment.pop('DOCUMENT_OCR_WEBHOOK_SECRET', None)
        runtime_config = Path(jobs) / 'benchmark-runtime.json'
        process = subprocess.Popen(
            [sys.executable, '-c', SERVER_BOOTSTRAP, str(listener.fileno()), str(runtime_config)], cwd=source,
            env=environment,
            pass_fds=(listener.fileno(),), stdout=output, stderr=subprocess.STDOUT)
        listener.close()
        try:
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',
                                        headers={'Authorization': 'Bearer ' + token},
                                        timeout=request_timeout, trust_env=False) as client:
                await wait_ready(client, process, startup_timeout)
                yield client, round((time.perf_counter() - started) * 1000, 2), environment, json.loads(runtime_config.read_text())
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


async def scan_request(client: httpx.AsyncClient, case: dict, data: bytes) -> tuple[dict, dict | None]:
    start = time.perf_counter()
    actual, error, status_code = None, None, None
    try:
        response = await client.post('/scan', files={'image':
            (Path(case['image']).name, data, mimetypes.guess_type(case['image'])[0] or 'image/jpeg')},
            data={key: str(value).lower() if isinstance(value, bool) else str(value)
                  for key, value in case.get('options', {}).items()})
        status_code = response.status_code
        actual, error = decode_scan(response)
    except httpx.TimeoutException:
        error = 'CLIENT_TIMEOUT'
    except httpx.HTTPError:
        error = 'HTTP_TRANSPORT_ERROR'
    elapsed = (time.perf_counter() - start) * 1000
    processing = actual['processingMs'] if actual is not None else None
    return {'elapsedMs': round(elapsed, 2), 'processingMs': processing,
            # Includes upload, queue wait, HTTP/serialization and measurement
            # differences; never label this as a directly measured queue time.
            'overheadAndQueueMs': round(max(0, elapsed - processing), 2) if processing is not None else None,
            'httpStatus': status_code, 'error': error}, actual


def timing(values: list[float]) -> dict:
    return {'medianMs': round(statistics.median(values), 2) if values else None,
            'p95Ms': percentile(values, 95), 'maxMs': max(values) if values else None}


def source_fingerprint(source: Path) -> str:
    files = [*sorted((source / 'core').glob('*.py')), source / 'deploy/docker/server.py']
    return hashlib.sha256(b''.join(str(p.relative_to(source)).encode() + b'\0' + p.read_bytes() for p in files)).hexdigest()


def scorer_fingerprint() -> str:
    return hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes()
        for name in ('multidoc_accuracy.py', 'public_accuracy.py', 'public_data.py'))).hexdigest()


def correctness_regressions(before: dict, after: dict) -> list[str]:
    checks = []
    for kind in ('fieldMatches', 'absentFieldMatches'):
        if before[kind].keys() != after[kind].keys():
            raise ValueError('incompatible HTTP field denominators')
        checks.extend((kind + ':' + key, value, after[kind][key]) for key, value in before[kind].items())
    checks.extend((key, before[key], after[key]) for key in ('mrzExact', 'routingMatch', 'negativeRejected'))
    checks.append(('statusSuccess', before['status'] == 'success', after['status'] == 'success'))
    for _, was, now in checks:
        if (was is None) != (now is None):
            raise ValueError('incompatible HTTP metric denominators')
    return [metric for metric, was, now in checks if was is True and now is False]


def compare(report: dict, baseline: dict) -> dict:
    """Require the same workload/configuration before comparing score booleans."""
    if any(value is False for value in baseline.get('runtimeIntegrity', {}).values()):
        raise ValueError('invalid HTTP baseline runtime integrity')
    for key in ('schemaVersion', 'caseCount', 'identityGroups', 'repeatsPerConcurrency', 'seed'):
        if report[key] != baseline[key]:
            raise ValueError('incompatible HTTP benchmark: ' + key)
    for key in ('manifestSha256', 'evaluatorSha256', 'scorerSha256', 'modelSha256', 'platform',
                'python', 'cpuCount', 'packages', 'kycLanguages', 'serverConfig', 'clientConfig'):
        if report['provenance'].get(key) is None or baseline['provenance'].get(key) is None:
            raise ValueError('missing HTTP benchmark provenance: ' + key)
        if report['provenance'][key] != baseline['provenance'][key]:
            raise ValueError('incompatible HTTP benchmark provenance: ' + key)
    if list(report['concurrency']) != list(baseline['concurrency']):
        raise ValueError('incompatible HTTP concurrency levels')
    regressions, latency, throughput = [], {}, {}
    for level, result in report['concurrency'].items():
        before = baseline['concurrency'][level]
        previous = {case['id']: case for case in before['cases']}
        current = {case['id']: case for case in result['cases']}
        if (len(previous) != len(before['cases']) or len(current) != len(result['cases'])
                or previous.keys() != current.keys()):
            raise ValueError('incompatible HTTP case IDs')
        matches = {}
        for identifier, case in current.items():
            old = previous[identifier]
            if any(case[key] != old[key] for key in ('profile', 'group')) or len(case['runs']) != len(old['runs']):
                raise ValueError('incompatible HTTP case metadata or repeats')
            for a, b in zip(old['runs'], case['runs']):
                regressions.extend({'concurrency': int(level), 'id': identifier, 'metric': metric}
                                   for metric in correctness_regressions(a, b))
                # Newly accepted documents must not be compared with an old
                # pre-OCR rejection. Stable rejections still consume capacity.
                if (a['runtimeError'] is None and b['runtimeError'] is None
                        and a['status'] == b['status'] and a['documentType'] == b['documentType']):
                    matches.setdefault(case['profile'], []).append((a['elapsedMs'], b['elapsedMs']))
        latency[level] = {}
        for kind in sorted({c['profile'] for c in current.values()}):
            pairs = matches.get(kind, [])
            entry = {'comparableCalls': len(pairs), 'measured': len(pairs) >= 5}
            latency[level][kind] = entry
            if len(pairs) < 5:
                continue
            old_times, new_times = zip(*pairs)
            for metric, function in [('medianMs', statistics.median), ('p95Ms', lambda xs: percentile(xs, 95))]:
                old_value, new_value = function(old_times), function(new_times)
                allowance = max(100, old_value * .20)
                entry[metric] = {'before': round(old_value, 2), 'after': round(new_value, 2),
                                 'allowanceMs': round(allowance, 2)}
                if new_value > old_value + allowance:
                    regressions.append({'concurrency': int(level), 'profile': kind, 'metric': 'REGRESSED_' + metric})
        throughput[level] = {'beforeRequestsPerSecond': before['requestsPerSecond'],
                             'afterRequestsPerSecond': result['requestsPerSecond'], 'gated': False}
    old_variants = {(item['id'], item['mode']): item for item in baseline.get('variantChecks', [])}
    new_variants = {(item['id'], item['mode']): item for item in report.get('variantChecks', [])}
    if old_variants.keys() != new_variants.keys():
        raise ValueError('incompatible HTTP format/hint/evidence checks')
    for key, item in new_variants.items():
        regressions.extend({'id': item['id'], 'mode': item['mode'], 'metric': metric}
                           for metric in correctness_regressions(old_variants[key]['score'], item['score']))
    unique = {json.dumps(item, sort_keys=True): item for item in regressions}
    return {'passed': report['operationalPassed'] and not regressions,
            'regressions': [unique[key] for key in sorted(unique)],
            'latencyComparison': latency, 'throughputComparison': throughput,
            'absoluteTargetsEvaluated': False}


async def variant_checks(client: httpx.AsyncClient, cases: list[dict], payloads: dict,
                         truths: dict, sequential: dict) -> list[dict]:
    """Score real encoded formats and explicit API options outside the load sweep."""
    registered = {item['documentType'] for item in (await client.get('/documents')).json()['documents']}
    output = []
    for kind in sorted({profile(c) for c in cases} & registered):
        # Freeze selection independently of scan success; clean contract fixtures
        # take precedence, then the manifest's existing order.
        candidates = [case for case in cases if profile(case) == kind]
        case = next((c for c in candidates if c.get('capture') == 'clean'), candidates[0])
        original = score(case, truths[case['id']], sequential[case['id']], 0, None)
        with Image.open(io.BytesIO(payloads[case['id']])) as image:
            pixels = image.convert('RGB')
        for mode in ('png', 'jpeg', 'raster_pdf', 'hinted', 'evidence'):
            upload_case = case
            data = payloads[case['id']]
            if mode in ('hinted', 'evidence'):
                options = {**case.get('options', {}), **({'document_type': kind} if mode == 'hinted'
                            else {'include_evidence': True})}
                upload_case = {**case, 'options': options}
            else:
                stream = io.BytesIO()
                if mode == 'raster_pdf':
                    pixels.save(stream, format='PDF', resolution=150)
                    suffix = '.pdf'
                elif mode == 'jpeg':
                    pixels.save(stream, format='JPEG', quality=95, subsampling=0)
                    suffix = '.jpg'
                else:
                    pixels.save(stream, format='PNG')
                    suffix = '.png'
                data = stream.getvalue()
                upload_case = {**case, 'image': str(Path(case['image']).with_suffix(suffix))}
            stats, actual = await scan_request(client, upload_case, data)
            result = score(case, truths[case['id']], actual, stats['elapsedMs'], stats['error'])
            output.append({'id': case['id'], 'profile': kind, 'mode': mode, 'score': result,
                           'httpStatus': stats['httpStatus'],
                           'regressionsVsAutomatic': correctness_regressions(original, result)})
        print('HTTP format/hint/evidence checks: ' + kind, flush=True)
    return output


async def route_checks(client: httpx.AsyncClient, cases: list[dict], payloads: dict, sequential: dict,
                       source: Path, environment: dict, request_timeout: float) -> dict:
    """Check real auth, capability discovery, batch order and grouped pages."""
    checks = {}
    checks['health'] = (await client.get('/health')).status_code == 200
    response = await client.get('/documents')
    body = response.json()
    checks['capabilities'] = (response.status_code == 200 and isinstance(body.get('documents'), list)
                               and bool(body['documents']))
    checks['authRequired'] = (await client.get('/documents', headers={'Authorization': ''})).status_code == 401
    checks['invalidUploadRejected'] = (await client.post('/scan', files={'image':
                                       ('invalid.txt', b'not an image', 'text/plain')})).status_code == 400
    checks['invalidHintRejected'] = (await client.post('/scan', data={'document_type': 'not-a-profile'},
                                   files={'image': ('invalid.jpg', b'x', 'image/jpeg')})).status_code == 400
    # Keep total multipart payload under the server's shared 10 MiB bound.
    chosen, size = [], 0
    for case in cases:
        if case.get('options') or sequential.get(case['id']) is None:
            continue
        if size + len(payloads[case['id']]) <= 10 * 1024**2:
            chosen.append(case)
            size += len(payloads[case['id']])
        if len(chosen) == 2:
            break
    if not chosen:
        raise ValueError('no comparable automatic cases for route checks')
    files = [('images', (Path(c['image']).name, payloads[c['id']],
                        mimetypes.guess_type(c['image'])[0] or 'image/jpeg')) for c in chosen]
    response = await client.post('/scan/batch', files=files)
    body = response.json()
    checks['batchMatchesSingle'] = (response.status_code == 200 and
        semantic_response(body.get('results')) == [sequential[c['id']] for c in chosen])
    case = next((c for c in cases if sequential.get(c['id'], {}) is not None
                 and sequential[c['id']].get('status') == 'success'
                 and len(payloads[c['id']]) <= 5 * 1024**2 and not c.get('options')), None)
    if case:
        upload = ('images', (Path(case['image']).name, payloads[case['id']],
                            mimetypes.guess_type(case['image'])[0] or 'image/jpeg'))
        # Grouped pages deliberately use the evidence extraction path internally.
        # Compare with that same /scan option, then remove evidence omitted by
        # the default grouped response, rather than equating distinct schemas.
        evidence_stats, evidence_actual = await scan_request(client,
            {**case, 'options': {'include_evidence': True}}, payloads[case['id']])
        if evidence_actual is not None:
            evidence_actual.pop('fieldEvidence', None)
            evidence_actual.pop('imageSize', None)
        response = await client.post('/scan/document', files=[upload, upload])
        body = response.json()
        checks['groupedDuplicateAgrees'] = (response.status_code == 200 and body.get('status') == 'success'
             and body.get('conflicts') == [] and len(body.get('results', [])) == 2
             and evidence_stats['error'] is None
             and all(semantic_response(r) == semantic_response(evidence_actual) for r in body['results']))
    else:
        checks['groupedDuplicateAgrees'] = None
    # Exercise upload -> encrypted local queue -> actual worker OCR -> polling
    # -> delete. A separate temporary queue prevents touching application jobs.
    response = await client.post('/jobs', files=[files[0]])
    body = response.json()
    checks['jobQueued'] = response.status_code == 202 and body.get('status') == 'queued'
    checks['jobResultMatchesSingle'] = False
    checks['jobDeleted'] = False
    if checks['jobQueued']:
        identifier = body['id']
        worker = subprocess.Popen([sys.executable, '-m', 'core.jobs', 'worker'], cwd=source, env=environment,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.perf_counter() + request_timeout
            while time.perf_counter() < deadline:
                response = await client.get('/jobs/' + identifier)
                body = response.json()
                if body.get('status') in {'succeeded', 'failed'}:
                    checks['jobResultMatchesSingle'] = (body['status'] == 'succeeded'
                         and semantic_response(body.get('result', {}).get('results')) == [sequential[chosen[0]['id']]])
                    break
                if worker.poll() is not None:
                    break
                await asyncio.sleep(.1)
            removed = await client.delete('/jobs/' + identifier)
            checks['jobDeleted'] = (removed.status_code in (200, 204)
                                    and (await client.get('/jobs/' + identifier)).status_code == 404)
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
    return checks


async def run(manifests: list[Path], root: Path, source: Path, concurrency: list[int], repeats: int,
              seed: int, case_limit: int | None, server_log: Path, startup_timeout: float,
              request_timeout: float, check_routes: bool = True) -> dict:
    cases = []
    for manifest in manifests:
        contents = json.loads(manifest.read_text())
        inspect_samples(contents, root)
        cases.extend(contents['cases'])
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('duplicate case IDs')
    cases = select_cases(cases, case_limit)
    if not concurrency or concurrency[0] != 1 or len(set(concurrency)) != len(concurrency):
        raise ValueError('concurrency must start with 1 and contain no duplicates')
    if any(value not in (1, 2, 4) for value in concurrency) or not 1 <= repeats <= 5:
        raise ValueError('concurrency must be 1/2/4; repeats must be 1..5')
    if len(cases) * len(concurrency) * repeats > 1000:
        raise ValueError('bounded smoke evaluation allows at most 1000 measured scan requests')
    truths = {case['id']: expected(case, root) for case in cases}
    payloads = {case['id']: (root / case['image']).read_bytes() for case in cases}
    model_directory = Path(importlib.util.find_spec('rapidocr').origin).parent / 'models'
    report = {'schemaVersion': 1, 'purpose': 'real loopback HTTP closed-loop evaluation; not a production SLA',
              'caseCount': len(cases), 'identityGroups': len({c['group'] for c in cases}),
              'repeatsPerConcurrency': repeats, 'seed': seed,
              'provenance': {'manifestSha256': [{'name': p.name, 'sha256': fingerprint(p)} for p in manifests],
                             'evaluatorSha256': fingerprint(Path(__file__)), 'sourceSha256': source_fingerprint(source),
                             'scorerSha256': scorer_fingerprint(),
                             'platform': platform.platform(), 'python': platform.python_version(),
                             'cpuCount': os.cpu_count(),
                             'kycLanguages': os.getenv('DOCUMENT_OCR_KYC_LANGS', ''),
                             'clientConfig': {'requestTimeoutSeconds': request_timeout,
                                              'startupTimeoutSeconds': startup_timeout,
                                              'routeChecks': check_routes},
                             'packages': {key: importlib.metadata.version(key) for key in
                                          ['rapidocr', 'onnxruntime', 'fastapi', 'uvicorn', 'httpx',
                                           'pillow', 'opencv-python', 'numpy', 'pypdfium2']}},
              'concurrency': {}, 'routeChecks': {}, 'variantChecks': []}
    sequential = {}
    async with local_server(source, server_log, startup_timeout, request_timeout) as (client, startup, environment, config):
        report['serverReadyMs'] = startup
        report['provenance']['serverConfig'] = config
        cold, _ = await scan_request(client, cases[0], payloads[cases[0]['id']])
        report['firstScan'] = cold
        for count in concurrency:
            records = {c['id']: {'id': c['id'], 'group': c['group'], 'profile': profile(c), 'runs': []} for c in cases}
            transport, inconsistencies = [], []
            semaphore = asyncio.Semaphore(count)

            async def measure(case, iteration):
                async with semaphore:
                    stats, actual = await scan_request(client, case, payloads[case['id']])
                    transport.append(stats)
                    result = score(case, truths[case['id']], actual, stats['elapsedMs'], stats['error'])
                    records[case['id']]['runs'].append(result)
                    semantic = semantic_response(actual)
                    if count == 1 and iteration == 0:
                        sequential[case['id']] = semantic
                    elif semantic != sequential[case['id']]:
                        inconsistencies.append({'id': case['id'], 'iteration': iteration})

            started = time.perf_counter()
            for iteration in range(repeats):
                order = list(cases)
                random.Random(seed + iteration).shuffle(order)
                await asyncio.gather(*(measure(case, iteration) for case in order))
                print(f'HTTP concurrency {count}: repeat {iteration + 1}/{repeats}, {len(cases)} cases', flush=True)
            duration = time.perf_counter() - started
            values = list(records.values())
            report['concurrency'][str(count)] = {
                'wallSeconds': round(duration, 3), 'requestsPerSecond': round(len(transport) / duration, 3),
                'overall': summarize(values),
                'profiles': {kind: summarize([c for c in values if c['profile'] == kind])
                             for kind in sorted({profile(c) for c in cases})},
                'serverProcessing': timing([r['processingMs'] for r in transport if r['processingMs'] is not None]),
                'overheadAndQueue': timing([r['overheadAndQueueMs'] for r in transport if r['overheadAndQueueMs'] is not None]),
                'httpStatuses': dict(Counter(str(r['httpStatus']) for r in transport)),
                'transportErrors': dict(Counter(r['error'] for r in transport if r['error'])),
                'inconsistentResponses': inconsistencies, 'cases': values}
        if check_routes:
            report['routeChecks'] = await route_checks(client, cases, payloads, sequential, source,
                                                       environment, request_timeout)
            report['variantChecks'] = await variant_checks(client, cases, payloads, truths, sequential)
    report['runtimeIntegrity'] = {
        'sourceUnchanged': report['provenance']['sourceSha256'] == source_fingerprint(source),
        'scorerUnchanged': report['provenance']['scorerSha256'] == scorer_fingerprint(),
        'evaluatorUnchanged': report['provenance']['evaluatorSha256'] == fingerprint(Path(__file__))}
    report['operationalPassed'] = (cold['error'] is None and all(report['runtimeIntegrity'].values())
        and all(value is True for value in report['routeChecks'].values())
        and all(not result['transportErrors'] and not result['inconsistentResponses']
                and not result['overall']['runtimeErrors'] for result in report['concurrency'].values())
        and all(item['score']['runtimeError'] is None and not item['regressionsVsAutomatic']
                for item in report['variantChecks']))
    report['provenance']['modelSha256'] = {p.name: fingerprint(p) for p in sorted(model_directory.glob('*.onnx'))}
    # Accuracy is reported independently. Stable incorrect outputs do not become
    # correct merely because the transport and concurrency checks passed.
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, action='append')
    parser.add_argument('--root', type=Path, default=SAMPLE_ROOT)
    parser.add_argument('--source', type=Path, default=REPO)
    parser.add_argument('--concurrency', type=int, nargs='+', default=[1, 2, 4])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20260908)
    parser.add_argument('--case-limit', type=int)
    parser.add_argument('--startup-timeout', type=float, default=120)
    parser.add_argument('--request-timeout', type=float, default=65)
    parser.add_argument('--skip-route-checks', action='store_true')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--server-log', type=Path, default=Path('benchmark-data/http/server.log'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.manifest or [SAMPLES, EXPANSION], args.root, args.source.resolve(),
        args.concurrency, args.repeats, args.seed, args.case_limit, args.server_log,
        args.startup_timeout, args.request_timeout, not args.skip_route_checks))
    if args.baseline:
        try:
            report['comparison'] = compare(report, json.loads(args.baseline.read_text()))
        except ValueError as exc:
            # Keep the new measurements reviewable even when the chosen
            # baseline is incompatible; never report such a run as an uplift.
            report['comparison'] = {'passed': False, 'compatible': False, 'error': str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'concurrency'}))
    return 0 if report.get('comparison', {'passed': report['operationalPassed']})['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
