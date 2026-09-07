from copy import deepcopy
import json

import pytest

from benchmarks.multidoc_accuracy import form_truth, gate, score, summarize


def policy():
    return {'minimumRepeats': 3, 'maxWarmP95Ms': 2500, 'maxLatencyIncreaseFraction': .2,
            'latencyNoiseFloorMs': 100, 'profiles': {'passport': {
                'minimumCases': 1, 'fieldAccuracy': .95, 'completeRecordAccuracy': .9, 'acceptedPositiveAccuracy': .9}}}


def report():
    run = {'absentFieldMatches': {}, 'fieldMatches': {'surname': True}, 'mrzExact': True, 'routingMatch': True,
           'status': 'success', 'documentType': 'passport', 'runtimeError': None,
           'negativeRejected': None, 'elapsedMs': 800}
    cases = [{'id': 'a', 'group': 'holder', 'profile': 'passport', 'runs': [deepcopy(run) for _ in range(3)]}]
    return {'schemaVersion': 1, 'seed': 1, 'policySha256': 'policy', 'repeats': 3,
            'profiles': {'passport': summarize(cases)}, 'cases': cases,
            'provenance': {k: 'same' for k in ('manifestSha256', 'scorerSha256', 'packages', 'modelSha256',
                                             'platform', 'python', 'cpuCount', 'kycLanguages')}}


def test_repeats_do_not_inflate_identity_or_case_counts():
    result = summarize(report()['cases'])
    assert result['cases'] == result['identityGroups'] == 1
    assert result['calls'] == result['fieldExpectations'] == 3
    assert result['unstableCases'] == 0


def test_instability_and_accuracy_failures_cannot_be_averaged_away():
    r = report()
    r['cases'][0]['runs'][0]['fieldMatches']['surname'] = False
    r['profiles']['passport'] = summarize(r['cases'])
    result = gate(r, policy())
    assert not result['passed']
    assert 'passport:ERROR_OR_INSTABILITY' in result['failures']
    assert 'passport:fieldAccuracy' in result['failures']


def test_negative_crashes_are_not_successful_rejections():
    case = {'profile': 'negative_control'}
    result = score(case, ({}, None), None, 5, 'RuntimeError')
    assert result['negativeRejected'] is False
    result = score(case, ({}, None), {'status': 'success'}, 5, None)
    assert result['negativeRejected'] is False


def test_unscored_families_do_not_get_perfect_accuracy():
    r = report()['cases'][0]
    for run in r['runs']:
        run['fieldMatches'] = {}
    summary = summarize([r])
    assert summary['fieldAccuracy'] is None
    assert summary['completeRecordAccuracy'] is None


def test_missing_family_and_too_few_runs_fail_closed():
    r = report()
    r['repeats'] = 1
    r['profiles'] = {}
    assert set(gate(r, policy())['failures']) == {'INSUFFICIENT_REPEATS', 'passport:INSUFFICIENT_CASES'}
    assert not gate(r, policy())['regressionPassed']


def test_latency_budget_is_per_family():
    r = report()
    r['profiles']['passport']['p95Ms'] = 3000
    assert 'passport:LATENCY_BUDGET' in gate(r, policy())['failures']


def test_correctness_regression_cannot_hide_inside_average():
    before = report()
    after = deepcopy(before)
    after['cases'][0]['runs'][0]['mrzExact'] = False
    assert gate(after, policy(), before)['regressions'] == [{'id': 'a', 'metric': 'mrzExact'}]


@pytest.mark.parametrize('key', ['manifestSha256', 'scorerSha256', 'modelSha256', 'packages'])
def test_comparison_rejects_mismatched_evaluation_provenance(key):
    before = report()
    after = deepcopy(before)
    after['provenance'][key] = 'changed'
    with pytest.raises(ValueError, match='provenance'):
        gate(after, policy(), before)


def test_publisher_linked_split_tin_is_joined_without_using_production_parser():
    labels = ['1 Name of entity/individual.', '2 Business name/disregarded entity name',
              '5 Address', '6 City, state, and ZIP code', 'Social security number',
              'Employer identification number']
    values = [['EXAMPLE PERSON'], [''], ['10 Example Road'], ['Example, NY 10000'], ['123', '45', '6789'], ['']]
    entities = []
    for i, (label, answers) in enumerate(zip(labels, values)):
        qid = i * 10
        entities.append({'id': qid, 'label': 'question', 'text': label,
                         'linking': [[qid, qid + j + 1] for j in range(len(answers))]})
        for j, answer in enumerate(answers):
            entities.append({'id': qid + j + 1, 'label': 'answer', 'text': answer, 'box': [j * 100, 0, j * 100 + 90, 30]})
    truth = form_truth({'funsd_json': json.dumps(entities)})
    assert truth['taxpayerId'] == '123456789'
    assert truth['taxpayerIdType'] == 'ssn'
    assert truth['businessName'] is None


def test_absent_optional_values_detect_hallucinations_without_free_accuracy_credit():
    case = {'profile': 'us_w9'}
    scored = score(case, ({'name': 'EXAMPLE', 'businessName': None}, None),
                   {'status': 'success', 'documentType': 'us_w9',
                    'documentFields': {'name': 'EXAMPLE', 'businessName': 'instruction text'}}, 100, None)
    assert scored['fieldMatches'] == {'name': True}
    assert scored['absentFieldMatches'] == {'businessName': False}
    summary = summarize([{'id': 'a', 'group': 'g', 'runs': [scored]}])
    assert summary['fieldExpectations'] == 1
    assert summary['spuriousFields'] == 1


def test_latency_comparison_excludes_newly_readable_previously_rejected_documents():
    before = report()
    after = deepcopy(before)
    for r in before['cases'][0]['runs']:
        r['status'] = 'failure'
        r['elapsedMs'] = 2
    result = gate(after, policy(), before)
    assert result['latencyComparison']['passport'] == {'comparableCalls': 0, 'measured': False}
    assert not any('REGRESSED_' in f for f in result['failures'])


def test_matched_successful_latency_regression_is_blocked():
    before = report()
    before['cases'][0]['runs'] *= 2
    after = deepcopy(before)
    for r in after['cases'][0]['runs']:
        r['elapsedMs'] = 1400
    result = gate(after, policy(), before)
    assert not result['regressionPassed']
    assert 'passport:REGRESSED_p95Ms' in result['failures']


def test_unchanged_rejection_latency_cannot_escape_regression_gate():
    before = report()
    before['cases'][0]['runs'] *= 2
    for run in before['cases'][0]['runs']:
        run.update(status='unsupported_page', fieldMatches={}, mrzExact=None,
                   routingMatch=None, negativeRejected=True)
    after = deepcopy(before)
    for run in after['cases'][0]['runs']:
        run['elapsedMs'] = 1800
    assert not gate(after, policy(), before)['regressionPassed']


def test_cold_start_failure_is_operational_even_when_warm_calls_succeed():
    r = report()
    r['coldStartError'] = 'OCRModelInitError'
    assert 'COLD_START_ERROR' in gate(r, policy())['failures']
    assert not gate(r, policy())['regressionPassed']


def test_mixed_source_baseline_cannot_approve_a_candidate():
    before, after = report(), report()
    before['sourceUnchanged'] = False
    with pytest.raises(ValueError, match='source changed'):
        gate(after, policy(), before)


def test_legacy_field_block_scores_actual_extraction_without_free_credit():
    case = {'profile': 'pan', 'fieldBlock': 'panFields'}
    actual = {'documentType': 'pan', 'status': 'failure', 'panFields': {'name': 'ANNA SAMPLE'}}
    r = score(case, ({'name': 'ANNA SAMPLE', 'panNumber': 'ABCPA1234F'}, None), actual, 100, None)
    assert r['fieldMatches'] == {'name': True, 'panNumber': False}
    assert summarize([{'group': 'one', 'runs': [r]}])['acceptedPositiveAccuracy'] == 0
