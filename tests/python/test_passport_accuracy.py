"""Regression tests for passport benchmark scoring, using synthetic results."""

from copy import deepcopy
import json

import pytest

from benchmarks.accuracy import evaluate_results, run_benchmark


def _results():
    biodata = {
        "status": "success",
        "documentType": "passport",
        "pageType": "passport_biodata",
        "fields": {"surname": "SYNTHETIC"},
        "mrzRaw": ["SYNTHETIC MRZ LINE ONE", "SYNTHETIC MRZ LINE TWO"],
        "mrzValid": True,
    }
    back = {
        "status": "success",
        "documentType": "passport",
        "pageType": "passport_non_biodata",
        "backPageFields": {"address": "SYNTHETIC ADDRESS"},
    }
    negative = {
        "status": "unsupported",
        "documentType": "unknown",
        "pageType": "unknown",
        "unsupportedReason": "not_passport",
    }
    return [
        (expected, {**deepcopy(expected), "processingMs": 100})
        for expected in (biodata, back, negative)
    ]


def test_complete_measurement_passes_without_copying_identity_values():
    report = evaluate_results(_results())

    assert report["passed"] is True
    assert report["metrics"]["fieldExpectations"] == 2
    assert report["metrics"]["fieldAccuracy"] == 1.0
    assert report["metrics"]["warmBiodataMedianMs"] == 100
    assert "SYNTHETIC" not in json.dumps(report)


@pytest.mark.parametrize("missing", ["fields", "mrz", "back", "biodata", "all"])
def test_missing_coverage_cannot_be_reported_as_perfect_accuracy(missing):
    results = _results()
    metric = {
        "fields": "fieldAccuracy",
        "mrz": "mrzExactRate",
        "back": "nonBiodataAccuracy",
        "biodata": "warmBiodataMedianMs",
        "all": "statusMatchRate",
    }[missing]
    if missing == "fields":
        for expected, _ in results:
            expected.pop("fields", None)
            expected.pop("backPageFields", None)
    elif missing == "mrz":
        results[0][0].pop("mrzRaw")
    elif missing == "back":
        results.pop(1)
    elif missing == "biodata":
        results.pop(0)
    else:
        results = []

    report = evaluate_results(results)

    assert report["passed"] is False
    assert report["metrics"][metric] is None
    assert any(check["metric"] == metric for check in report["failures"])


@pytest.mark.parametrize(
    ("sample_index", "key", "wrong_value"),
    [(0, "mrzValid", False), (2, "unsupportedReason", "wrong_reason")],
)
def test_annotated_metadata_participates_in_release_gate(sample_index, key, wrong_value):
    results = _results()
    results[sample_index][1][key] = wrong_value

    report = evaluate_results(results)

    assert report["passed"] is False
    assert report["metrics"]["statusMatchRate"] == 2 / 3


def test_back_page_field_error_fails_field_accuracy_gate():
    results = _results()
    results[1][1]["backPageFields"]["address"] = "WRONG SYNTHETIC ADDRESS"

    report = evaluate_results(results)

    assert report["metrics"]["fieldAccuracy"] == 0.5
    assert report["passed"] is False


def test_rejected_back_page_does_not_satisfy_positive_coverage():
    results = _results()
    expected, actual = results[1]
    expected["status"] = actual["status"] = "failure"

    report = evaluate_results(results)

    assert report["metrics"]["nonBiodataAccuracy"] is None
    assert report["passed"] is False


def test_wrong_classification_cannot_receive_field_or_mrz_credit():
    results = _results()
    results[0][1]["documentType"] = "pan"

    report = evaluate_results(results)

    assert report["metrics"]["fieldAccuracy"] == 0.5
    assert report["metrics"]["mrzExactRate"] == 0.0


@pytest.mark.parametrize("latency", [None, 0, -1, True, float("nan"), float("inf")])
def test_invalid_biodata_latency_fails_measurement_gate(latency):
    results = _results()
    results[0][1]["processingMs"] = latency

    report = evaluate_results(results)

    assert report["passed"] is False
    assert report["metrics"]["biodataLatencySamples"] == 0


def test_missing_latency_for_one_biodata_image_cannot_hide_behind_median():
    results = _results()
    expected, actual = deepcopy(results[0])
    actual.pop("processingMs")
    results.append((expected, actual))

    report = evaluate_results(results)

    assert report["metrics"]["warmBiodataMedianMs"] == 100
    assert report["passed"] is False
    assert any(
        check["metric"] == "biodataLatencySamples" for check in report["failures"]
    )


def test_runner_warms_once_and_records_crashes_without_identity_values(tmp_path):
    fixtures = _results()
    manifest = {f"sample-{index}.bin": expected for index, (expected, _) in enumerate(fixtures)}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    for filename in manifest:
        (tmp_path / filename).touch()
    calls = []

    def scanner(filename):
        calls.append(filename)
        if filename.endswith("sample-2.bin"):
            raise RuntimeError("SYNTHETIC PRIVATE VALUE")
        index = int(filename.rsplit("sample-", 1)[1].split(".")[0])
        return fixtures[index][1]

    report = run_benchmark(tmp_path, scanner)

    assert len(calls) == len(manifest) + 1
    assert calls[0] == calls[1]
    assert report["metrics"]["runtimeErrors"] == 1
    assert report["metrics"]["statusMatchRate"] == 2 / 3
    assert report["passed"] is False
    assert "SYNTHETIC PRIVATE VALUE" not in json.dumps(report)


def test_runner_validates_all_assets_before_calling_scanner(tmp_path):
    fixtures = _results()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "present.bin": fixtures[0][0], "missing.bin": fixtures[1][0],
    }))
    (tmp_path / "present.bin").touch()
    calls = []

    with pytest.raises(ValueError, match="assets must exist"):
        run_benchmark(tmp_path, lambda filename: calls.append(filename))

    assert calls == []
