"""HTTP evaluator failure-accounting tests; real capacity requires the CLI."""
import asyncio
import copy
from email import policy
from email.parser import BytesParser
import io
import json
from unittest.mock import Mock

import httpx
import pytest

from benchmarks.http_accuracy import compare, decode_scan, scan_request, select_cases, semantic_response, variant_checks, wait_ready


def result(**changes):
    return {'status': 'success', 'documentType': 'pan', 'processingMs': 10,
            'missingRequiredFields': [], **changes}


@pytest.mark.parametrize('response,error', [
    (httpx.Response(200, text='<html>proxy error</html>'), 'INVALID_JSON'),
    (httpx.Response(504, json={'error': 'SCAN_TIMEOUT'}), 'HTTP_504'),
    (httpx.Response(200, json=[]), 'INVALID_SCAN_RESPONSE'),
    (httpx.Response(200, json=result(processingMs=-1)), 'INVALID_SCAN_RESPONSE'),
    (httpx.Response(200, json=result(processingMs=True)), 'INVALID_SCAN_RESPONSE'),
    (httpx.Response(200, json=result(documentFields=['invalid'])), 'INVALID_SCAN_RESPONSE'),
    (httpx.Response(200, json=result(status='failure')), 'HTTP_STATUS_MISMATCH'),
    (httpx.Response(422, json=result()), 'HTTP_STATUS_MISMATCH'),
])
def test_invalid_http_outputs_are_failures(response, error):
    assert decode_scan(response) == (None, error)


def test_expected_quality_rejection_is_a_valid_ocr_response():
    actual = result(status='failure')
    assert decode_scan(httpx.Response(422, json=actual)) == (actual, None)


async def test_client_timeout_is_counted_without_exposing_document_fields():
    def timeout(request):
        raise httpx.ReadTimeout('sensitive server detail', request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout), base_url='http://loopback') as client:
        stats, actual = await scan_request(client, {'id': 'test', 'image': 'test.jpg'}, b'private image bytes')
    assert actual is None
    assert stats['error'] == 'CLIENT_TIMEOUT'
    assert stats['httpStatus'] is None
    assert 'sensitive' not in json.dumps(stats)
    assert 'private' not in json.dumps(stats)


async def test_real_request_contract_uses_multipart_and_hints():
    def handler(request):
        assert request.url.path == '/scan'
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        assert b'name="image"; filename="test.pdf"' in request.content
        assert b'Content-Type: application/pdf' in request.content
        assert b'name="document_type"' in request.content
        assert b'us_i94' in request.content
        return httpx.Response(200, json=result())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://loopback') as client:
        stats, actual = await scan_request(client,
            {'id': 'test', 'image': 'test.pdf', 'options': {'document_type': 'us_i94'}}, b'%PDF-1.7')
    assert stats['error'] is None
    assert actual['status'] == 'success'


async def test_model_setup_failure_stops_before_repeated_requests():
    process = Mock()
    process.poll.return_value = None
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503,
                json={'status': 'model_init_failed', 'error': 'private path'})), base_url='http://loopback') as client:
        with pytest.raises(RuntimeError, match='^MODEL_INIT_FAILED'):
            await wait_ready(client, process, 5)


async def test_startup_timeout_is_bounded():
    process = Mock()
    process.poll.return_value = None
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503,
                json={'status': 'loading'})), base_url='http://loopback') as client:
        with pytest.raises(TimeoutError, match='HTTP_SERVER_STARTUP_TIMEOUT'):
            await asyncio.wait_for(wait_ready(client, process, .01), 1)


def test_consistency_ignores_timing_but_preserves_extraction_and_errors():
    before = result(documentFields={'name': 'TEST'}, errors=[])
    assert semantic_response(before) == semantic_response({**before, 'processingMs': 20})
    assert semantic_response(before) != semantic_response({**before, 'documentFields': {'name': 'WRONG'}})
    assert semantic_response(before) != semantic_response({**before, 'errors': ['SCAN_ERROR']})


def test_case_cap_cannot_silently_omit_a_document_family():
    cases = [{'id': str(i), 'profile': kind} for i, kind in enumerate(['pan', 'pan', 'aadhaar', 'visa'])]
    assert {case['profile'] for case in select_cases(cases, 3)} == {'pan', 'aadhaar', 'visa'}
    with pytest.raises(ValueError, match='every profile'):
        select_cases(cases, 2)


def comparison_report():
    cases = [{'id': str(i), 'group': str(i), 'profile': 'pan', 'runs': [{
        'fieldMatches': {'name': True}, 'absentFieldMatches': {'fatherName': True},
        'mrzExact': None, 'routingMatch': True, 'negativeRejected': None,
        'status': 'success', 'documentType': 'pan', 'runtimeError': None, 'elapsedMs': 100}]} for i in range(5)]
    return {'schemaVersion': 1, 'caseCount': 5, 'identityGroups': 5, 'repeatsPerConcurrency': 1, 'seed': 1,
            'provenance': {key: 'same' for key in ('manifestSha256', 'evaluatorSha256', 'scorerSha256',
                'modelSha256', 'platform', 'python', 'cpuCount', 'packages', 'kycLanguages',
                'serverConfig', 'clientConfig')},
            'runtimeIntegrity': {'sourceUnchanged': True, 'scorerUnchanged': True, 'evaluatorUnchanged': True},
            'concurrency': {'1': {'cases': cases, 'requestsPerSecond': 10}}, 'operationalPassed': True}


def test_better_average_cannot_hide_one_previously_correct_field_regression():
    before = comparison_report()
    after = copy.deepcopy(before)
    after['concurrency']['1']['cases'][0]['runs'][0]['fieldMatches']['name'] = False
    comparison = compare(after, before)
    assert not comparison['passed']
    assert comparison['regressions'] == [{'concurrency': 1, 'id': '0', 'metric': 'fieldMatches:name'}]


@pytest.mark.parametrize('key', ['modelSha256', 'scorerSha256', 'serverConfig', 'clientConfig', 'manifestSha256'])
def test_mismatched_provenance_cannot_be_used_as_improvement_evidence(key):
    before, after = comparison_report(), comparison_report()
    after['provenance'][key] = 'changed'
    with pytest.raises(ValueError, match='incompatible HTTP benchmark provenance: ' + key):
        compare(after, before)


def test_matching_outcome_latency_regression_fails_with_fixed_noise_allowance():
    before, after = comparison_report(), comparison_report()
    for case in after['concurrency']['1']['cases']:
        case['runs'][0]['elapsedMs'] = 201
    comparison = compare(after, before)
    assert not comparison['passed']
    assert {item['metric'] for item in comparison['regressions']} == {'REGRESSED_medianMs', 'REGRESSED_p95Ms'}
    assert comparison['latencyComparison']['1']['pan']['p95Ms']['allowanceMs'] == 100


def test_new_success_is_not_compared_to_fast_pre_ocr_rejection():
    before, after = comparison_report(), comparison_report()
    for case in before['concurrency']['1']['cases']:
        case['runs'][0].update(status='failure', documentType='unknown', elapsedMs=1,
                               routingMatch=False, fieldMatches={'name': False})
    comparison = compare(after, before)
    assert comparison['passed']
    assert comparison['latencyComparison']['1']['pan'] == {'comparableCalls': 0, 'measured': False}


def test_changed_field_denominator_is_not_silently_compared():
    before, after = comparison_report(), comparison_report()
    del after['concurrency']['1']['cases'][0]['runs'][0]['fieldMatches']['name']
    with pytest.raises(ValueError, match='incompatible HTTP field denominators'):
        compare(after, before)


@pytest.mark.parametrize('key', ['sourceUnchanged', 'scorerUnchanged', 'evaluatorUnchanged'])
def test_mixed_source_baseline_cannot_be_used_as_regression_evidence(key):
    before, after = comparison_report(), comparison_report()
    before['runtimeIntegrity'][key] = False
    before['operationalPassed'] = False
    with pytest.raises(ValueError, match='invalid HTTP baseline runtime integrity'):
        compare(after, before)


def test_known_baseline_accuracy_or_format_failure_can_be_improved():
    before, after = comparison_report(), comparison_report()
    before['operationalPassed'] = False
    assert compare(after, before)['passed']


async def test_format_checks_send_real_encodings_and_do_not_omit_hint_or_evidence_modes():
    from PIL import Image
    import pypdfium2

    stream = io.BytesIO()
    Image.new('RGB', (100, 80), 'white').save(stream, format='PNG')
    actual = result(documentType='us_w9', documentFields={'name': 'TEST'})
    observed = []

    def handler(request):
        if request.url.path == '/documents':
            return httpx.Response(200, json={'documents': [{'documentType': 'us_w9'}]})
        message = BytesParser(policy=policy.default).parsebytes(
            b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
        parts = {part.get_param('name', header='content-disposition'): part for part in message.iter_parts()}
        content_type = parts['image'].get_content_type()
        data = parts['image'].get_payload(decode=True)
        if content_type == 'application/pdf':
            with pypdfium2.PdfDocument(data) as pdf:
                assert len(pdf) == 1
                page = pdf[0]
                text = page.get_textpage()
                try:
                    assert text.count_chars() == 0
                finally:
                    text.close()
                    page.close()
        else:
            with Image.open(io.BytesIO(data)) as image:
                assert image.format in ('PNG', 'JPEG')
        observed.append((content_type, set(parts)))
        return httpx.Response(200, json=actual)

    case = {'id': 'test', 'profile': 'us_w9', 'capture': 'clean', 'image': 'test.png'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://loopback') as client:
        checks = await variant_checks(client, [case], {'test': stream.getvalue()},
                                      {'test': ({'name': 'TEST'}, None)}, {'test': actual})
    assert [item['mode'] for item in checks] == ['png', 'jpeg', 'raster_pdf', 'hinted', 'evidence']
    assert all(item['score']['fieldMatches'] == {'name': True} for item in checks)
    assert all(not item['regressionsVsAutomatic'] for item in checks)
    assert [kind for kind, _ in observed[:3]] == ['image/png', 'image/jpeg', 'application/pdf']
    assert 'document_type' in observed[3][1]
    assert 'include_evidence' in observed[4][1]
