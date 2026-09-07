from copy import deepcopy
import pytest
from benchmarks.compare_public_accuracy import compare_reports


def report():
    return {'scoringVersion': 1, 'provenance': {
        'scorerSha256': 's', 'packages': {}, 'modelSha256': {}, 'kycLanguages': '',
        'platform': 'test', 'python': 'test', 'cpuCount': 1, 'coreSha256': 'code',
        'integrity': {'manifestSha256': 'data'}},
        'cases': [{'id': 'a', 'fieldMatches': {'name': True, 'number': False},
                   'mrzExact': False, 'status': 'success', 'runtimeError': None}],
        'hintedCases': [], 'passport': {}}


def test_improvement_cannot_hide_a_regression_in_another_field():
    before = report(); after = deepcopy(before)
    after['cases'][0]['fieldMatches'] = {'name': False, 'number': True}
    result = compare_reports(before, after)
    assert result['improvedCaseIds'] == ['a']
    assert result['regressedCaseIds'] == ['a']
    assert not result['passed']


@pytest.mark.parametrize('key', ['modelSha256', 'scorerSha256', 'packages'])
def test_changed_settings_require_separate_comparison(key):
    before = report(); after = deepcopy(before)
    after['provenance'][key] = 'different'
    with pytest.raises(ValueError, match='provenance'):
        compare_reports(before, after)


def test_cannot_remove_failing_field_to_raise_accuracy():
    before = report(); after = deepcopy(before)
    del after['cases'][0]['fieldMatches']['number']
    with pytest.raises(ValueError, match='expectations'):
        compare_reports(before, after)


def test_corpus_change_is_not_an_ocr_improvement():
    before = report(); after = deepcopy(before)
    after['provenance']['integrity']['manifestSha256'] = 'different'
    with pytest.raises(ValueError, match='manifests'):
        compare_reports(before, after)
