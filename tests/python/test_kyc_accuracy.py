"""Tests for the private KYC accuracy evaluator.

All fixtures are empty temporary files and synthetic dictionaries. No identity
documents or real personal values are used.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from benchmarks.kyc_accuracy import (
    DOCUMENT_FIELD_BLOCKS,
    DOCUMENT_TYPES,
    ManifestError,
    evaluate_manifest,
    field_block_for,
    normalize_value,
    validate_manifest,
)


def _thresholds(**overall_overrides):
    overall = {
        "minClassificationAccuracy": 0.0,
        "minExpectedAcceptanceRate": 0.0,
        "minExactFieldAccuracy": 0.0,
        "minNormalizedFieldAccuracy": 0.0,
        "minCompleteRecordAccuracy": 0.0,
        "minNormalizedCompleteRecordAccuracy": 0.0,
        "maxFalseSuccessRate": 1.0,
        "maxRuntimeErrorRate": 0.0,
    }
    overall.update(overall_overrides)
    return {"overall": overall}


def _sample(
    document_type: str,
    *,
    sample_id: str | None = None,
    accepted: bool = True,
    expected_value: str = "SYNTHETIC 123",
    design_family: str = "synthetic_v1",
):
    fields = {"identifier": expected_value} if accepted else {}
    return {
        "id": sample_id or f"{document_type}-001",
        "asset": f"{sample_id or document_type}.bin",
        "documentType": document_type,
        "designFamily": design_family,
        "yearBand": "synthetic-2026",
        "issuer": {
            "name": "synthetic-issuer",
            "state": "not_applicable",
        },
        "languages": ["en"],
        "scripts": ["Latin"],
        "side": "front",
        "capture": {
            "type": "other",
            "quality": {
                "resolution": "high",
                "blur": "none",
                "glare": "none",
                "rotation": "upright",
                "crop": "full",
                "perspective": "flat",
                "compression": "none",
            },
        },
        "expected": {
            "accepted": accepted,
            "fields": fields,
            "requiredFields": ["identifier"] if accepted else [],
        },
    }


def _manifest():
    samples = [_sample(document_type) for document_type in DOCUMENT_TYPES]
    # A valid accuracy dataset needs a real denominator for false-success rate.
    samples.append(
        _sample(
            "pan",
            sample_id="pan-negative-control",
            accepted=False,
        )
    )
    samples[-1]["expected"]["classificationTarget"] = "unknown"
    return {
        "schemaVersion": 1,
        "datasetVersion": "synthetic-test-v1",
        "requiredDocumentTypes": list(DOCUMENT_TYPES),
        "requiredSlices": {
            "designFamily": ["synthetic_v1"],
            "captureType": ["other"],
        },
        "requiredDocumentSlices": {
            document_type: {
                "designFamily": ["synthetic_v1"],
                "script": ["Latin"],
            }
            for document_type in DOCUMENT_TYPES
        },
        "thresholds": _thresholds(),
        "samples": samples,
    }


def _create_assets(manifest, root: Path):
    for sample in manifest["samples"]:
        path = root / sample["asset"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def _successful_results(manifest):
    results = {}
    for sample in manifest["samples"]:
        result = {
            "status": "success" if sample["expected"]["accepted"] else "failure",
            "documentType": sample["expected"].get(
                "classificationTarget", sample["documentType"]
            ),
        }
        if sample["expected"]["accepted"]:
            result[DOCUMENT_FIELD_BLOCKS[sample["documentType"]]] = dict(
                sample["expected"]["fields"]
            )
        results[sample["id"]] = result
    return results


def _scanner_for(manifest, results):
    ids_by_asset = {
        Path(sample["asset"]).name: sample["id"] for sample in manifest["samples"]
    }

    def scanner(path):
        return results[ids_by_asset[Path(path).name]]

    return scanner


def test_field_block_mapping_includes_current_and_future_types():
    assert field_block_for("pan") == "panFields"
    assert field_block_for("aadhaar") == "aadhaarFields"
    assert field_block_for("driving_licence") == "drivingLicenceFields"
    assert field_block_for("voter_id") == "voterIdFields"
    assert field_block_for("nrega_job_card") == "nregaJobCardFields"
    assert field_block_for("npr_letter") == "nprLetterFields"


def test_manifest_fails_closed_when_empty():
    manifest = _manifest()
    manifest["samples"] = []
    with pytest.raises(ManifestError, match="must not be empty"):
        validate_manifest(manifest)


def test_manifest_fails_closed_when_a_document_type_is_missing():
    manifest = _manifest()
    manifest["samples"] = [
        sample
        for sample in manifest["samples"]
        if sample["documentType"] != "npr_letter"
    ]
    with pytest.raises(ManifestError, match="npr_letter"):
        validate_manifest(manifest)


def test_negative_control_does_not_satisfy_positive_document_coverage():
    manifest = _manifest()
    npr = next(
        sample
        for sample in manifest["samples"]
        if sample["documentType"] == "npr_letter"
    )
    npr["expected"] = {
        "accepted": False,
        "classificationTarget": "unknown",
        "fields": {},
        "requiredFields": [],
    }

    with pytest.raises(ManifestError, match="accepted positive.*npr_letter"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("capture", "type"), "typo"),
        (("capture", "quality", "blur"), "typo"),
    ],
)
def test_manual_validation_enforces_schema_enums(path, value):
    manifest = _manifest()
    target = manifest["samples"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ManifestError, match="is invalid"):
        validate_manifest(manifest)


def test_accepted_required_field_cannot_be_null():
    manifest = _manifest()
    manifest["samples"][0]["expected"]["fields"]["identifier"] = None
    with pytest.raises(ManifestError, match="must not be null"):
        validate_manifest(manifest)


def test_accepted_sample_cannot_target_unknown_classification():
    manifest = _manifest()
    manifest["samples"][0]["expected"]["classificationTarget"] = "unknown"
    with pytest.raises(ManifestError, match="must target classification"):
        validate_manifest(manifest)


def test_required_variant_slice_fails_closed_when_missing():
    manifest = _manifest()
    manifest["requiredSlices"]["designFamily"].append("not_represented")
    with pytest.raises(ManifestError, match="not_represented"):
        validate_manifest(manifest)


def test_required_document_slice_fails_when_one_family_omits_variant():
    manifest = _manifest()
    pan = next(
        sample
        for sample in manifest["samples"]
        if sample["documentType"] == "pan"
        and sample["expected"]["accepted"]
    )
    pan["scripts"].append("Devanagari")
    manifest["requiredSlices"]["script"] = ["Latin", "Devanagari"]
    manifest["requiredDocumentSlices"]["aadhaar"]["script"] = [
        "Latin",
        "Devanagari",
    ]

    with pytest.raises(
        ManifestError,
        match="requiredDocumentSlices.aadhaar.script.*Devanagari",
    ):
        validate_manifest(manifest)


def test_normalization_is_unicode_aware_and_punctuation_insensitive():
    assert normalize_value("  ABC-123 ") == normalize_value("abc 123")
    assert normalize_value("नाम: सीमा") == normalize_value("नाम सीमा")
    assert normalize_value("ABC-123") != normalize_value("ABC-124")
    assert normalize_value(
        [{"name": "SYNTHETIC PERSON", "age": 39}]
    ) == normalize_value(
        [{"name": "synthetic-person", "age": 39}]
    )


@pytest.mark.parametrize(("first", "second"), [("दल", "दाल"), ("क", "क्"), ("க", "கா")])
def test_normalization_preserves_script_marks_that_change_identity(first, second):
    assert normalize_value(first) != normalize_value(second)


@pytest.mark.parametrize("key", ["languages", "scripts"])
def test_duplicate_metadata_cannot_inflate_slice_sample_counts(key):
    manifest = _manifest()
    values = manifest["samples"][0][key]
    values.append(values[0])

    with pytest.raises(ManifestError, match=f"{key} must not contain duplicates"):
        validate_manifest(manifest)


def test_evaluator_reads_every_document_specific_field_block(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["passed"] is True
    assert report["summary"]["samples"] == len(DOCUMENT_TYPES) + 1
    assert report["summary"]["classificationAccuracy"] == 1.0
    assert report["summary"]["exactFieldAccuracy"] == 1.0
    assert report["summary"]["completeRecordAccuracy"] == 1.0
    for document_type in DOCUMENT_TYPES:
        expected_samples = 2 if document_type == "pan" else 1
        assert report["documents"][document_type]["samples"] == expected_samples
        assert (
            report["documents"][document_type]["fields"]["identifier"][
                "exactAccuracy"
            ]
            == 1.0
        )


def test_exact_and_normalized_metrics_are_reported_separately(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    pan_id = next(
        sample["id"]
        for sample in manifest["samples"]
        if sample["documentType"] == "pan"
    )
    results[pan_id]["panFields"]["identifier"] = "synthetic-123"

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["summary"]["exactFieldAccuracy"] < 1.0
    assert report["summary"]["normalizedFieldAccuracy"] == 1.0
    assert report["summary"]["completeRecordAccuracy"] < 1.0
    assert report["summary"]["normalizedCompleteRecordAccuracy"] == 1.0


def test_false_success_is_counted_and_can_fail_a_threshold(tmp_path):
    manifest = _manifest()
    rejected = next(
        sample
        for sample in manifest["samples"]
        if sample["id"] == "pan-negative-control"
    )
    manifest["thresholds"] = _thresholds(maxFalseSuccessRate=0.0)
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    results[rejected["id"]] = {
        "status": "success",
        "documentType": "pan",
        "panFields": {"name": "SYNTHETIC FALSE SUCCESS"},
    }

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["passed"] is False
    assert report["summary"]["expectedRejected"] == 1
    assert report["summary"]["falseSuccesses"] == 1
    assert report["summary"]["falseSuccessRate"] == 1.0
    assert any(
        failure["rule"] == "maxFalseSuccessRate"
        for failure in report["failures"]
    )


def test_report_contains_metadata_and_document_slices(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["slices"]["designFamily"]["synthetic_v1"]["samples"] == 7
    assert report["slices"]["yearBand"]["synthetic-2026"]["samples"] == 7
    assert report["slices"]["quality.rotation"]["upright"]["samples"] == 7
    assert (
        report["documentSlices"]["aadhaar"]["script"]["Latin"]["samples"] == 1
    )


def test_runtime_error_is_recorded_without_exposing_exception_text(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    scanner = _scanner_for(manifest, results)
    failing_asset = Path(manifest["samples"][0]["asset"]).name

    def scanner_with_failure(path):
        if Path(path).name == failing_asset:
            raise RuntimeError("private value must not appear in report")
        return scanner(path)

    report = evaluate_manifest(
        manifest,
        scanner_with_failure,
        dataset_root=tmp_path,
    )

    assert report["passed"] is False
    assert report["summary"]["runtimeErrors"] == 1
    assert "private value" not in str(report)
    assert any(sample["runtimeError"] for sample in report["samples"])


def test_wrong_document_classification_penalizes_fields_and_complete_record(
    tmp_path,
):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    pan_sample = next(
        sample for sample in manifest["samples"] if sample["documentType"] == "pan"
    )
    results[pan_sample["id"]]["documentType"] = "aadhaar"

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["summary"]["classificationAccuracy"] < 1.0
    assert report["documents"]["pan"]["exactFieldAccuracy"] == 0.0
    assert report["documents"]["pan"]["completeRecordAccuracy"] == 0.0


def test_per_slice_minimum_sample_gate_is_configurable(tmp_path):
    manifest = _manifest()
    manifest["thresholds"]["perSlice"] = {
        "dimensions": ["designFamily"],
        "minimumSamples": 8,
        "rules": {},
    }
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert report["passed"] is False
    assert any(
        failure["rule"] == "minimumSamples"
        and failure["scope"] == "slice:designFamily=synthetic_v1"
        for failure in report["failures"]
    )


def test_slice_minimum_is_also_gated_per_document(tmp_path):
    manifest = _manifest()
    manifest["thresholds"]["perSlice"] = {
        "dimensions": ["designFamily"],
        "minimumSamples": 2,
        "rules": {},
    }
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
    )

    assert any(
        check["scope"] == "slice:designFamily=synthetic_v1"
        and check["rule"] == "minimumSamples"
        and check["passed"] is True
        for check in report["checks"]
    )
    assert any(
        failure["scope"]
        == "document-slice:aadhaar:designFamily=synthetic_v1"
        and failure["rule"] == "minimumSamples"
        for failure in report["failures"]
    )


def test_threshold_override_replaces_manifest_thresholds(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    strict = deepcopy(_thresholds())
    strict["overall"]["minClassificationAccuracy"] = 1.0
    pan_id = next(
        sample["id"]
        for sample in manifest["samples"]
        if sample["documentType"] == "pan"
    )
    results[pan_id]["documentType"] = "aadhaar"

    report = evaluate_manifest(
        manifest,
        _scanner_for(manifest, results),
        dataset_root=tmp_path,
        thresholds=strict,
    )

    assert report["passed"] is False
    assert any(
        failure["rule"] == "minClassificationAccuracy"
        for failure in report["failures"]
    )


def test_release_thresholds_use_unrounded_measurements(tmp_path):
    manifest = _manifest()
    manifest["thresholds"] = _thresholds(minExactFieldAccuracy=0.6666669)
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    for sample in manifest["samples"][:2]:
        results[sample["id"]][DOCUMENT_FIELD_BLOCKS[sample["documentType"]]] = {}

    report = evaluate_manifest(
        manifest, _scanner_for(manifest, results), dataset_root=tmp_path
    )

    assert report["summary"]["exactFieldAccuracy"] == 4 / 6
    assert any(
        failure["rule"] == "minExactFieldAccuracy"
        for failure in report["failures"]
    )


def test_wrong_classification_cannot_get_credit_for_absent_fields(tmp_path):
    manifest = _manifest()
    sample = manifest["samples"][0]
    sample["expected"]["fields"]["optionalField"] = None
    _create_assets(manifest, tmp_path)
    results = _successful_results(manifest)
    results[sample["id"]]["documentType"] = "aadhaar"

    report = evaluate_manifest(
        manifest, _scanner_for(manifest, results), dataset_root=tmp_path
    )

    fields = report["samples"][0]["fields"]
    assert fields["optionalField"]["exact"] is False
    assert fields["optionalField"]["normalized"] is False


def test_scanner_crash_is_not_a_correct_unknown_classification(tmp_path):
    manifest = _manifest()
    _create_assets(manifest, tmp_path)
    scanner = _scanner_for(manifest, _successful_results(manifest))
    negative = manifest["samples"][-1]

    def scanner_with_crash(path):
        if Path(path).name == negative["asset"]:
            raise RuntimeError("synthetic failure")
        return scanner(path)

    report = evaluate_manifest(manifest, scanner_with_crash, dataset_root=tmp_path)

    assert report["summary"]["classificationCorrect"] == len(DOCUMENT_TYPES)
    assert report["samples"][-1]["classificationCorrect"] is False
    assert report["samples"][-1]["runtimeError"] is True
