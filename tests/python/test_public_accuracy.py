import pytest

from benchmarks.public_accuracy import aggregate, evaluate, score_case

CASE = {'id': 'opaque/1', 'group': 'identity/1', 'dataset': 'midv-2020'}


def test_wrong_route_cannot_earn_field_or_mrz_credit():
    result = score_case(CASE, {'surname': 'TEST'}, ['a', 'b'], {
        'elapsedMs': 12, 'actual': {'documentType': 'us_driver_license',
                                  'fields': {'surname': 'TEST'}, 'mrzRaw': ['a', 'b']}})
    assert result['fieldMatches'] == {'surname': False}
    assert result['mrzExact'] is False


def test_partial_failure_keeps_correct_fields_but_not_status_success():
    result = score_case(CASE, {'surname': 'TEST', 'dateOfBirth': '900101'}, ['a', 'b'], {
        'elapsedMs': 12, 'actual': {'status': 'failure', 'documentType': 'passport',
                                  'fields': {'surname': 'TEST', 'dateOfBirth': '1990-01-01'}}})
    assert result['allScoredFieldsExact'] is True
    assert result['mrzExact'] is False
    report = aggregate([result])
    assert report['fieldAccuracy'] == 1
    assert report['statuses'] == {'failure': 1}


def test_crashes_and_missing_fields_count_in_denominator_without_raw_text():
    result = score_case(CASE, {'surname': 'SECRET'}, ['a', 'b'], {
        'elapsedMs': 12, 'actual': None, 'errorType': 'RuntimeError'})
    report = aggregate([result])
    assert report['fieldExpectations'] == 1
    assert report['fieldAccuracy'] == 0
    assert report['runtimeErrors'] == 1
    assert 'SECRET' not in str(result)


def test_unscored_families_have_no_accuracy_denominator():
    result = score_case(CASE, {}, None, {'elapsedMs': 1, 'actual': {'status': 'unsupported_page'}})
    report = aggregate([result])
    assert report['fieldAccuracy'] is None
    assert report['scoredCases'] == 0


def test_identity_count_does_not_count_capture_views_twice():
    a = score_case(CASE, {}, None, {'elapsedMs': 1, 'actual': {}})
    b = {**a, 'id': 'opaque/2', 'elapsedMs': 5}
    report = aggregate([a, b])
    assert report['identityGroups'] == 1
    assert report['medianMs'] == 3
    assert report['p95Ms'] == 5


def test_missing_or_reordered_results_fail_closed(tmp_path):
    with pytest.raises(ValueError, match='IDs/order'):
        evaluate({'cases': [CASE]}, tmp_path, {'cases': []})
