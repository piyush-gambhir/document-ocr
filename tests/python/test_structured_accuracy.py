import copy
import json
from pathlib import Path

import pytest

from benchmarks.structured_accuracy import (
    DATE_FIELDS, DOCUMENT_TYPES, IDENTIFIER_FIELDS, ManifestError, PROFILES,
    evaluate_manifest, validate_manifest,
)


def _manifest():
    quality = {"resolution": "high", "blur": "none", "glare": "none", "rotation": "upright", "crop": "full", "perspective": "flat", "compression": "none"}
    samples = []
    for kind in DOCUMENT_TYPES:
        fields = {}
        for name in PROFILES[kind]["requiredFields"]:
            fields[name] = "2030-06-01" if name in DATE_FIELDS else "000123456" if name in IDENTIFIER_FIELDS[kind] else "SYNTHETIC NAME"
        for accepted in (True, False):
            suffix = "positive" if accepted else "negative"
            samples.append({
                "id": f"{kind}-{suffix}", "groupId": f"group-{kind}-{suffix}",
                "asset": f"{kind}-{suffix}.png", "documentType": kind,
                "designFamily": "synthetic_evaluator_test", "yearBand": "synthetic",
                "issuer": {"name": "synthetic", "state": "not_applicable"},
                "languages": ["en"], "scripts": ["Latin"], "side": "single_page",
                "capture": {"type": "phone_photo", "quality": quality},
                "expected": {"accepted": accepted, "classificationTarget": kind if accepted else "unknown", "fields": fields if accepted else {}, "requiredFields": list(fields) if accepted else []},
            })
    return {
        "schemaVersion": 1, "datasetVersion": "synthetic-tests-only", "split": "release",
        "requiredDocumentTypes": list(DOCUMENT_TYPES),
        "minimumIndependentGroups": {"positive": 1, "negative": 1},
        "requiredSlices": {"captureType": ["phone_photo"]},
        "requiredDocumentSlices": {kind: {"designFamily": ["synthetic_evaluator_test"]} for kind in DOCUMENT_TYPES},
        "thresholds": {"overall": {
            "minClassificationAccuracy": 1, "minExpectedAcceptanceRate": 1,
            "minExactFieldAccuracy": 1, "minNormalizedFieldAccuracy": 1,
            "minCompleteRecordAccuracy": 1, "minNormalizedCompleteRecordAccuracy": 1,
            "maxFalseSuccessRate": 0, "maxRuntimeErrorRate": 0,
        }},
        "structuredThresholds": {"minIdentifierExactAccuracy": 1, "minDateExactAccuracy": 1},
        "samples": samples,
    }


def _setup(tmp_path, manifest):
    results = {}
    for sample in manifest["samples"]:
        (tmp_path / sample["asset"]).write_bytes(b"evaluator fixture; not an image")
        results[sample["asset"]] = {"status": "success" if sample["expected"]["accepted"] else "failure", "documentType": sample["expected"]["classificationTarget"], "documentFields": copy.deepcopy(sample["expected"]["fields"])}
    return results, lambda path: results[Path(path).name]


def test_all_profiles_read_document_fields_with_exact_group_metrics(tmp_path):
    manifest = _manifest()
    results, scanner = _setup(tmp_path, manifest)
    report = evaluate_manifest(manifest, scanner, dataset_root=tmp_path)
    assert report["passed"]
    assert report["summary"]["identifierExactAccuracy"] == 1
    assert report["summary"]["dateExactAccuracy"] == 1
    assert report["documents"]["us_w9"]["dateExactAccuracy"] is None
    assert report["documents"]["us_ead"]["independentPositiveGroups"] == 1
    assert "000123456" not in json.dumps(report)


@pytest.mark.parametrize("change", [
    lambda m: m["samples"].pop(),
    lambda m: m["samples"][0].pop("groupId"),
    lambda m: m["samples"][0].update(split="tuning"),
    lambda m: m["minimumIndependentGroups"].update(positive=2),
    lambda m: m["samples"][0]["expected"]["fields"].update(documentNumber=""),
    lambda m: m["samples"][0]["expected"]["fields"].update(surname="  "),
    lambda m: m["samples"][0]["expected"]["fields"].update(documentNumber=123456),
    lambda m: m["samples"][0]["expected"]["fields"].update(dateOfBirth="2023-02-29"),
    lambda m: m["samples"][0]["expected"]["fields"].update(dateOfBirth="06/01/2030"),
    lambda m: m["samples"][0]["expected"]["requiredFields"].remove("documentNumber"),
    lambda m: m["samples"][1]["expected"].update(classificationTarget="us_driver_license"),
    lambda m: m["samples"][1].update(groupId=m["samples"][0]["groupId"]),
    lambda m: m["samples"][1].update(asset=m["samples"][0]["asset"]),
])
def test_incomplete_or_misleading_coverage_fails_closed(change):
    manifest = _manifest()
    change(manifest)
    with pytest.raises(ManifestError):
        validate_manifest(manifest)


def test_null_optional_annotations_cannot_inflate_accuracy(tmp_path):
    manifest = _manifest()
    manifest["samples"][0]["expected"]["fields"]["issueDate"] = None
    results, scanner = _setup(tmp_path, manifest)
    results[manifest["samples"][0]["asset"]]["documentFields"]["documentNumber"] = "123456"
    report = evaluate_manifest(manifest, scanner, dataset_root=tmp_path)
    assert report["absentFieldAnnotationsExcluded"] == 1
    assert "issueDate" not in report["samples"][0]["fields"]
    assert report["summary"]["identifierExactAccuracy"] < 1
    assert not report["passed"]


def test_strict_identifier_and_date_gates_survive_loose_normalized_gates(tmp_path):
    manifest = _manifest()
    manifest["thresholds"]["overall"]["minExactFieldAccuracy"] = 0
    manifest["thresholds"]["overall"]["minCompleteRecordAccuracy"] = 0
    results, scanner = _setup(tmp_path, manifest)
    fields = results[manifest["samples"][0]["asset"]]["documentFields"]
    fields["documentNumber"] = "000-123456"
    fields["dateOfBirth"] = "20300601"
    report = evaluate_manifest(manifest, scanner, dataset_root=tmp_path)
    assert report["summary"]["normalizedFieldAccuracy"] == 1
    assert not report["passed"]
    assert {"minIdentifierExactAccuracy", "minDateExactAccuracy"} <= {item["rule"] for item in report["failures"]}


def test_missing_wrong_type_and_crash_do_not_receive_field_credit(tmp_path):
    manifest = _manifest()
    results, scanner = _setup(tmp_path, manifest)
    results[manifest["samples"][0]["asset"]]["documentType"] = "passport"
    negative = manifest["samples"][1]["asset"]
    def failing_scan(path):
        if Path(path).name == negative:
            raise RuntimeError("private content not for report")
        return scanner(path)
    report = evaluate_manifest(manifest, failing_scan, dataset_root=tmp_path)
    assert report["documents"]["us_driver_license"]["identifierExactAccuracy"] == 0
    assert report["samples"][1]["classificationCorrect"] is False
    assert report["summary"]["runtimeErrors"] == 1
    assert "private content" not in json.dumps(report)
    assert not report["passed"]


def test_false_acceptance_of_negative_control_fails(tmp_path):
    manifest = _manifest()
    results, scanner = _setup(tmp_path, manifest)
    results[manifest["samples"][1]["asset"]]["status"] = "success"
    report = evaluate_manifest(manifest, scanner, dataset_root=tmp_path)
    assert report["summary"]["falseSuccesses"] == 1
    assert not report["passed"]


def test_unmeasured_example_manifest_cannot_pass(capsys):
    from benchmarks.structured_accuracy import main
    example = Path(__file__).resolve().parents[2] / "benchmarks" / "structured_manifest.example.json"
    assert main(["--manifest", str(example)]) == 2
    assert "samples must not be empty" in capsys.readouterr().err
