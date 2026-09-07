#!/usr/bin/env python3
"""Private, end-to-end accuracy benchmark for non-passport KYC documents.

The evaluator is intentionally dependency-light. It accepts a versioned JSON
manifest, calls an injected scanner for every private asset, selects the result
field block for the expected document type, and emits a JSON-safe report.

Raw expected or extracted values are never copied into the report. Per-sample
details contain only identifiers, booleans, and field names so benchmark reports
can be retained without duplicating identity data.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


MANIFEST_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1

DOCUMENT_FIELD_BLOCKS: dict[str, str] = {
    "pan": "panFields",
    "aadhaar": "aadhaarFields",
    "driving_licence": "drivingLicenceFields",
    "voter_id": "voterIdFields",
    "nrega_job_card": "nregaJobCardFields",
    "npr_letter": "nprLetterFields",
}
DOCUMENT_TYPES = tuple(DOCUMENT_FIELD_BLOCKS)

SINGLE_VALUE_SLICE_DIMENSIONS = {
    "designFamily",
    "yearBand",
    "issuer",
    "state",
    "side",
    "captureType",
    "quality.resolution",
    "quality.blur",
    "quality.glare",
    "quality.rotation",
    "quality.crop",
    "quality.perspective",
    "quality.compression",
}
MULTI_VALUE_SLICE_DIMENSIONS = {"language", "script"}
SLICE_DIMENSIONS = SINGLE_VALUE_SLICE_DIMENSIONS | MULTI_VALUE_SLICE_DIMENSIONS

CAPTURE_TYPES = frozenset(
    {
        "flatbed_scan",
        "phone_photo",
        "screenshot",
        "native_pdf",
        "photocopy",
        "other",
    }
)
QUALITY_VALUES: dict[str, frozenset[str]] = {
    "resolution": frozenset({"low", "medium", "high", "native_pdf"}),
    "blur": frozenset({"none", "mild", "severe"}),
    "glare": frozenset({"none", "mild", "severe"}),
    "rotation": frozenset(
        {"upright", "minor_skew", "quarter_turn", "upside_down"}
    ),
    "crop": frozenset({"full", "tight", "partial"}),
    "perspective": frozenset({"flat", "mild", "severe"}),
    "compression": frozenset({"none", "mild", "severe"}),
}

THRESHOLD_RULES: dict[str, tuple[str, str]] = {
    "minClassificationAccuracy": ("classificationAccuracy", "min"),
    "minExpectedAcceptanceRate": ("expectedAcceptanceRate", "min"),
    "minExactFieldAccuracy": ("exactFieldAccuracy", "min"),
    "minNormalizedFieldAccuracy": ("normalizedFieldAccuracy", "min"),
    "minCompleteRecordAccuracy": ("completeRecordAccuracy", "min"),
    "minNormalizedCompleteRecordAccuracy": (
        "normalizedCompleteRecordAccuracy",
        "min",
    ),
    "maxFalseSuccessRate": ("falseSuccessRate", "max"),
    "maxRuntimeErrorRate": ("runtimeErrorRate", "max"),
}
REQUIRED_OVERALL_THRESHOLD_RULES = frozenset(THRESHOLD_RULES)


class ManifestError(ValueError):
    """Raised when a KYC benchmark manifest is incomplete or inconsistent."""


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    # Gate on the measured ratio; display rounding can otherwise turn a value
    # just below a release threshold into a passing result.
    return numerator / denominator


def normalize_value(value: Any) -> Any:
    """Normalize a field value for tolerant comparison.

    String normalization is Unicode-aware, case-insensitive, and removes
    whitespace/punctuation while preserving letters, digits, and combining
    marks from every script. Exact comparison remains available separately.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return "".join(
            character
            for character in normalized
            if character.isalnum() or unicodedata.category(character).startswith("M")
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(normalize_value(item) for item in value)
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), normalize_value(item)) for key, item in value.items())
        )
    return normalize_value(str(value))


def field_block_for(document_type: str) -> str:
    """Return the camel-case result block for a supported KYC document type."""

    try:
        return DOCUMENT_FIELD_BLOCKS[document_type]
    except KeyError as exc:
        raise ManifestError(f"Unsupported KYC document type: {document_type}") from exc


def _result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if not isinstance(converted, Mapping):
            raise TypeError("scanner result to_dict() must return a mapping")
        return dict(converted)
    raise TypeError("scanner result must be a mapping or provide to_dict()")


def result_fields_for(result: Mapping[str, Any], document_type: str) -> dict[str, Any]:
    """Read the correct field block for ``document_type`` from a scan result."""

    block = result.get(field_block_for(document_type))
    return dict(block) if isinstance(block, Mapping) else {}


@dataclass(frozen=True)
class FieldOutcome:
    exact: bool
    normalized: bool
    present: bool


@dataclass(frozen=True)
class Observation:
    sample_id: str
    expected_document_type: str
    actual_document_type: str
    expected_accepted: bool
    actual_accepted: bool
    runtime_error: bool
    field_outcomes: Mapping[str, FieldOutcome]
    required_fields: tuple[str, ...]

    @property
    def classification_correct(self) -> bool:
        return (
            not self.runtime_error
            and self.actual_document_type == self.expected_document_type
        )

    @property
    def false_success(self) -> bool:
        return not self.expected_accepted and self.actual_accepted

    @property
    def false_rejection(self) -> bool:
        return self.expected_accepted and not self.actual_accepted

    @property
    def complete_record_exact(self) -> bool:
        return (
            self.expected_accepted
            and self.actual_accepted
            and self.classification_correct
            and all(self.field_outcomes[name].exact for name in self.required_fields)
        )

    @property
    def complete_record_normalized(self) -> bool:
        return (
            self.expected_accepted
            and self.actual_accepted
            and self.classification_correct
            and all(self.field_outcomes[name].normalized for name in self.required_fields)
        )


@dataclass
class FieldCounter:
    expected: int = 0
    present: int = 0
    exact: int = 0
    normalized: int = 0

    def add(self, outcome: FieldOutcome) -> None:
        self.expected += 1
        self.present += int(outcome.present)
        self.exact += int(outcome.exact)
        self.normalized += int(outcome.normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "present": self.present,
            "exactMatches": self.exact,
            "normalizedMatches": self.normalized,
            "exactAccuracy": _ratio(self.exact, self.expected),
            "normalizedAccuracy": _ratio(self.normalized, self.expected),
        }


@dataclass
class MetricAccumulator:
    total: int = 0
    classification_correct: int = 0
    expected_accepted: int = 0
    actual_accepted: int = 0
    accepted_expected: int = 0
    expected_rejected: int = 0
    false_successes: int = 0
    false_rejections: int = 0
    runtime_errors: int = 0
    complete_records_exact: int = 0
    complete_records_normalized: int = 0
    fields: dict[str, FieldCounter] = field(
        default_factory=lambda: defaultdict(FieldCounter)
    )

    def add(self, observation: Observation, *, field_prefix: str = "") -> None:
        self.total += 1
        self.classification_correct += int(observation.classification_correct)
        self.expected_accepted += int(observation.expected_accepted)
        self.actual_accepted += int(observation.actual_accepted)
        self.accepted_expected += int(
            observation.expected_accepted and observation.actual_accepted
        )
        self.expected_rejected += int(not observation.expected_accepted)
        self.false_successes += int(observation.false_success)
        self.false_rejections += int(observation.false_rejection)
        self.runtime_errors += int(observation.runtime_error)
        self.complete_records_exact += int(observation.complete_record_exact)
        self.complete_records_normalized += int(
            observation.complete_record_normalized
        )

        for name, outcome in observation.field_outcomes.items():
            output_name = f"{field_prefix}{name}"
            self.fields[output_name].add(outcome)

    def to_dict(self) -> dict[str, Any]:
        field_expected = sum(counter.expected for counter in self.fields.values())
        field_exact = sum(counter.exact for counter in self.fields.values())
        field_normalized = sum(counter.normalized for counter in self.fields.values())
        return {
            "samples": self.total,
            "classificationCorrect": self.classification_correct,
            "classificationAccuracy": _ratio(
                self.classification_correct, self.total
            ),
            "expectedAccepted": self.expected_accepted,
            "actualAccepted": self.actual_accepted,
            "actualAcceptanceRate": _ratio(self.actual_accepted, self.total),
            "expectedAcceptanceRate": _ratio(
                self.accepted_expected, self.expected_accepted
            ),
            "falseRejections": self.false_rejections,
            "falseRejectionRate": _ratio(
                self.false_rejections, self.expected_accepted
            ),
            "expectedRejected": self.expected_rejected,
            "falseSuccesses": self.false_successes,
            "falseSuccessRate": _ratio(
                self.false_successes, self.expected_rejected
            ),
            "runtimeErrors": self.runtime_errors,
            "runtimeErrorRate": _ratio(self.runtime_errors, self.total),
            "fieldExpectations": field_expected,
            "exactFieldMatches": field_exact,
            "normalizedFieldMatches": field_normalized,
            "exactFieldAccuracy": _ratio(field_exact, field_expected),
            "normalizedFieldAccuracy": _ratio(
                field_normalized, field_expected
            ),
            "completeRecordMatches": self.complete_records_exact,
            "completeRecordAccuracy": _ratio(
                self.complete_records_exact, self.expected_accepted
            ),
            "normalizedCompleteRecordMatches": self.complete_records_normalized,
            "normalizedCompleteRecordAccuracy": _ratio(
                self.complete_records_normalized, self.expected_accepted
            ),
            "fields": {
                name: counter.to_dict()
                for name, counter in sorted(self.fields.items())
            },
        }


def _expect_type(
    value: Any,
    expected_type: type | tuple[type, ...],
    location: str,
) -> None:
    if not isinstance(value, expected_type):
        raise ManifestError(f"{location} has the wrong type")


def _validate_threshold_rules(rules: Any, location: str, *, require_all: bool) -> None:
    _expect_type(rules, Mapping, location)
    unknown = set(rules) - set(THRESHOLD_RULES)
    if unknown:
        raise ManifestError(
            f"{location} contains unknown threshold rules: {sorted(unknown)}"
        )
    if require_all:
        missing = REQUIRED_OVERALL_THRESHOLD_RULES - set(rules)
        if missing:
            raise ManifestError(
                f"{location} is missing threshold rules: {sorted(missing)}"
            )
    for name, value in rules.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ManifestError(f"{location}.{name} must be a number")
        if not 0 <= float(value) <= 1:
            raise ManifestError(f"{location}.{name} must be between 0 and 1")


def _validate_required_slice_coverage(
    requirements: Any,
    observed: Mapping[str, set[str]],
    location: str,
) -> None:
    _expect_type(requirements, Mapping, location)
    if not requirements:
        raise ManifestError(f"{location} must not be empty")
    for dimension, values in requirements.items():
        if dimension not in SLICE_DIMENSIONS:
            raise ManifestError(f"{location} has unknown dimension: {dimension}")
        _expect_type(values, list, f"{location}.{dimension}")
        if (
            not values
            or any(
                not isinstance(value, str) or not value.strip()
                for value in values
            )
            or len(values) != len(set(values))
        ):
            raise ManifestError(
                f"{location}.{dimension} must contain unique non-empty strings"
            )
        missing_values = set(values) - observed.get(dimension, set())
        if missing_values:
            raise ManifestError(
                f"{location}.{dimension} has no accepted positive samples for: "
                + ", ".join(sorted(missing_values))
            )


def validate_manifest(manifest: Any, *, field_blocks: Mapping[str, str] | None = None) -> None:
    """Validate required structure and dataset coverage without extra packages."""

    field_blocks = DOCUMENT_FIELD_BLOCKS if field_blocks is None else field_blocks
    document_types = tuple(field_blocks)
    _expect_type(manifest, Mapping, "manifest")
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            f"schemaVersion must be {MANIFEST_SCHEMA_VERSION}"
        )
    if not isinstance(manifest.get("datasetVersion"), str) or not manifest[
        "datasetVersion"
    ].strip():
        raise ManifestError("datasetVersion must be a non-empty string")

    required_types = manifest.get("requiredDocumentTypes")
    _expect_type(required_types, list, "requiredDocumentTypes")
    if len(required_types) != len(set(required_types)):
        raise ManifestError("requiredDocumentTypes must not contain duplicates")
    if set(required_types) != set(document_types):
        raise ManifestError(
            "requiredDocumentTypes must contain every supported KYC document type: "
            + ", ".join(document_types)
        )

    samples = manifest.get("samples")
    _expect_type(samples, list, "samples")
    if not samples:
        raise ManifestError("samples must not be empty")

    sample_ids: set[str] = set()
    observed_positive_types: set[str] = set()
    observed_slices: dict[str, set[str]] = defaultdict(set)
    observed_document_slices: dict[
        str,
        dict[str, set[str]],
    ] = {
        document_type: defaultdict(set)
        for document_type in document_types
    }

    for index, sample in enumerate(samples):
        location = f"samples[{index}]"
        _expect_type(sample, Mapping, location)
        for key in (
            "id",
            "asset",
            "documentType",
            "designFamily",
            "yearBand",
            "issuer",
            "languages",
            "scripts",
            "side",
            "capture",
            "expected",
        ):
            if key not in sample:
                raise ManifestError(f"{location}.{key} is required")

        sample_id = sample["id"]
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise ManifestError(f"{location}.id must be a non-empty string")
        if sample_id in sample_ids:
            raise ManifestError(f"duplicate sample id: {sample_id}")
        sample_ids.add(sample_id)

        asset = sample["asset"]
        if not isinstance(asset, str) or not asset.strip():
            raise ManifestError(f"{location}.asset must be a non-empty string")
        asset_path = Path(asset)
        if asset_path.is_absolute() or ".." in asset_path.parts:
            raise ManifestError(
                f"{location}.asset must be a safe path relative to the dataset root"
            )

        document_type = sample["documentType"]
        if document_type not in field_blocks:
            raise ManifestError(
                f"{location}.documentType is unsupported: {document_type}"
            )
        for key in ("designFamily", "yearBand"):
            if not isinstance(sample[key], str) or not sample[key].strip():
                raise ManifestError(f"{location}.{key} must be a non-empty string")

        issuer = sample["issuer"]
        _expect_type(issuer, Mapping, f"{location}.issuer")
        for key in ("name", "state"):
            if not isinstance(issuer.get(key), str) or not issuer[key].strip():
                raise ManifestError(
                    f"{location}.issuer.{key} must be a non-empty string"
                )

        for key in ("languages", "scripts"):
            values = sample[key]
            _expect_type(values, list, f"{location}.{key}")
            if not values or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ManifestError(
                    f"{location}.{key} must contain non-empty strings"
                )
            if len(values) != len(set(values)):
                raise ManifestError(f"{location}.{key} must not contain duplicates")

        if sample["side"] not in {
            "front",
            "back",
            "both",
            "single_page",
            "multi_page",
        }:
            raise ManifestError(f"{location}.side is invalid")

        capture = sample["capture"]
        _expect_type(capture, Mapping, f"{location}.capture")
        if capture.get("type") not in CAPTURE_TYPES:
            raise ManifestError(
                f"{location}.capture.type is invalid: {capture.get('type')}"
            )
        quality = capture.get("quality")
        _expect_type(quality, Mapping, f"{location}.capture.quality")
        for key, allowed_values in QUALITY_VALUES.items():
            if quality.get(key) not in allowed_values:
                raise ManifestError(
                    f"{location}.capture.quality.{key} is invalid: "
                    f"{quality.get(key)}"
                )

        expected = sample["expected"]
        _expect_type(expected, Mapping, f"{location}.expected")
        if not isinstance(expected.get("accepted"), bool):
            raise ManifestError(f"{location}.expected.accepted must be boolean")
        fields = expected.get("fields")
        _expect_type(fields, Mapping, f"{location}.expected.fields")
        for field_name, field_value in fields.items():
            if not isinstance(field_name, str) or not field_name.strip():
                raise ManifestError(
                    f"{location}.expected.fields keys must be non-empty strings"
                )
            if not _is_json_field_value(field_value):
                raise ManifestError(
                    f"{location}.expected.fields.{field_name} must be JSON-compatible"
                )
        required_fields = expected.get("requiredFields")
        _expect_type(required_fields, list, f"{location}.expected.requiredFields")
        if len(required_fields) != len(set(required_fields)):
            raise ManifestError(
                f"{location}.expected.requiredFields contains duplicates"
            )
        unknown_required = set(required_fields) - set(fields)
        if unknown_required:
            raise ManifestError(
                f"{location}.expected.requiredFields are missing from fields: "
                f"{sorted(unknown_required)}"
            )
        if expected["accepted"] and (not fields or not required_fields):
            raise ManifestError(
                f"{location}.expected accepted samples need fields and requiredFields"
            )
        if expected["accepted"]:
            null_required = [
                name for name in required_fields if fields.get(name) is None
            ]
            if null_required:
                raise ManifestError(
                    f"{location}.expected required fields must not be null: "
                    f"{sorted(null_required)}"
                )
        classification_target = expected.get(
            "classificationTarget", document_type
        )
        if classification_target not in (*document_types, "unknown"):
            raise ManifestError(
                f"{location}.expected.classificationTarget is unsupported: "
                f"{classification_target}"
            )
        if expected["accepted"] and classification_target != document_type:
            raise ManifestError(
                f"{location}.expected accepted samples must target "
                f"classification {document_type}"
            )
        if expected["accepted"]:
            observed_positive_types.add(document_type)
            for dimension, values in _sample_slice_values(sample).items():
                observed_slices[dimension].update(values)
                observed_document_slices[document_type][dimension].update(
                    values
                )

    missing_types = set(required_types) - observed_positive_types
    if missing_types:
        raise ManifestError(
            "manifest has no accepted positive samples for required "
            "document types: "
            + ", ".join(sorted(missing_types))
        )

    _validate_required_slice_coverage(
        manifest.get("requiredSlices"),
        observed_slices,
        "requiredSlices",
    )

    required_document_slices = manifest.get("requiredDocumentSlices")
    _expect_type(
        required_document_slices,
        Mapping,
        "requiredDocumentSlices",
    )
    configured_types = set(required_document_slices)
    expected_types = set(required_types)
    if configured_types != expected_types:
        missing = expected_types - configured_types
        unknown = configured_types - expected_types
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise ManifestError(
            "requiredDocumentSlices must configure every required document "
            "type: " + "; ".join(details)
        )
    for document_type, requirements in required_document_slices.items():
        _validate_required_slice_coverage(
            requirements,
            observed_document_slices[document_type],
            f"requiredDocumentSlices.{document_type}",
        )

    thresholds = manifest.get("thresholds")
    _expect_type(thresholds, Mapping, "thresholds")
    _validate_threshold_rules(
        thresholds.get("overall"), "thresholds.overall", require_all=True
    )

    per_document = thresholds.get("perDocument", {})
    _expect_type(per_document, Mapping, "thresholds.perDocument")
    for document_type, rules in per_document.items():
        if document_type != "*" and document_type not in field_blocks:
            raise ManifestError(
                f"thresholds.perDocument has unknown type: {document_type}"
            )
        _validate_threshold_rules(
            rules,
            f"thresholds.perDocument.{document_type}",
            require_all=False,
        )

    per_slice = thresholds.get("perSlice")
    if per_slice is not None:
        _expect_type(per_slice, Mapping, "thresholds.perSlice")
        dimensions = per_slice.get("dimensions")
        _expect_type(dimensions, list, "thresholds.perSlice.dimensions")
        if not dimensions:
            raise ManifestError("thresholds.perSlice.dimensions must not be empty")
        unknown_dimensions = set(dimensions) - SLICE_DIMENSIONS
        if unknown_dimensions:
            raise ManifestError(
                "thresholds.perSlice has unknown dimensions: "
                + ", ".join(sorted(unknown_dimensions))
            )
        minimum_samples = per_slice.get("minimumSamples")
        if (
            isinstance(minimum_samples, bool)
            or not isinstance(minimum_samples, int)
            or minimum_samples < 1
        ):
            raise ManifestError(
                "thresholds.perSlice.minimumSamples must be a positive integer"
            )
        _validate_threshold_rules(
            per_slice.get("rules", {}),
            "thresholds.perSlice.rules",
            require_all=False,
        )


def _is_json_field_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, list):
        return all(_is_json_field_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _is_json_field_value(item)
            for key, item in value.items()
        )
    return False


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Could not load manifest {manifest_path}: {exc}") from exc
    validate_manifest(manifest)
    return manifest


def _sample_slice_values(sample: Mapping[str, Any]) -> dict[str, list[str]]:
    issuer = sample["issuer"]
    capture = sample["capture"]
    quality = capture["quality"]
    return {
        "designFamily": [sample["designFamily"]],
        "yearBand": [sample["yearBand"]],
        "issuer": [issuer["name"]],
        "state": [issuer["state"]],
        "language": list(sample["languages"]),
        "script": list(sample["scripts"]),
        "side": [sample["side"]],
        "captureType": [capture["type"]],
        **{
            f"quality.{name}": [quality[name]]
            for name in (
                "resolution",
                "blur",
                "glare",
                "rotation",
                "crop",
                "perspective",
                "compression",
            )
        },
    }


def _compare(
    sample: Mapping[str, Any],
    raw_result: Any,
    *,
    runtime_error: bool,
    field_blocks: Mapping[str, str] | None = None,
) -> Observation:
    field_blocks = DOCUMENT_FIELD_BLOCKS if field_blocks is None else field_blocks
    result = _result_to_dict(raw_result)
    document_type = sample["documentType"]
    expected = sample["expected"]
    expected_document_type = expected.get(
        "classificationTarget", document_type
    )
    actual_document_type = str(result.get("documentType", "unknown"))
    actual_accepted = result.get("status") == "success"

    # A classification error is an end-to-end extraction error, even if a
    # malformed result happens to populate the expected document block.
    classification_correct = (
        not runtime_error and actual_document_type == expected_document_type
    )
    actual_fields = (
        result.get(field_blocks[document_type], {})
        if actual_document_type == document_type
        else {}
    )

    if not isinstance(actual_fields, Mapping):
        actual_fields = {}
    outcomes: dict[str, FieldOutcome] = {}
    for name, expected_value in expected["fields"].items():
        present = name in actual_fields and actual_fields[name] is not None
        actual_value = actual_fields.get(name)
        outcomes[name] = FieldOutcome(
            exact=classification_correct and actual_value == expected_value,
            normalized=classification_correct
            and normalize_value(actual_value) == normalize_value(expected_value),
            present=present,
        )

    return Observation(
        sample_id=sample["id"],
        expected_document_type=expected_document_type,
        actual_document_type=actual_document_type,
        expected_accepted=expected["accepted"],
        actual_accepted=actual_accepted,
        runtime_error=runtime_error,
        field_outcomes=outcomes,
        required_fields=tuple(expected["requiredFields"]),
    )


def _threshold_checks(
    metrics: Mapping[str, Any],
    rules: Mapping[str, Any],
    scope: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rule_name, threshold in rules.items():
        metric_name, direction = THRESHOLD_RULES[rule_name]
        actual = metrics.get(metric_name)
        if actual is None:
            passed = False
        elif direction == "min":
            passed = actual >= threshold
        else:
            passed = actual <= threshold
        checks.append(
            {
                "scope": scope,
                "rule": rule_name,
                "metric": metric_name,
                "actual": actual,
                "threshold": threshold,
                "operator": ">=" if direction == "min" else "<=",
                "passed": passed,
            }
        )
    return checks


def evaluate_manifest(
    manifest: Mapping[str, Any],
    scanner: Callable[[str], Any],
    *,
    dataset_root: str | Path,
    thresholds: Mapping[str, Any] | None = None,
    field_blocks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate a validated private dataset with an injected scanner."""

    field_blocks = DOCUMENT_FIELD_BLOCKS if field_blocks is None else field_blocks
    document_types = tuple(field_blocks)
    validate_manifest(manifest, field_blocks=field_blocks)
    root = Path(dataset_root)
    threshold_config = dict(
        manifest["thresholds"] if thresholds is None else thresholds
    )
    # Reuse full manifest validation for override validation without changing
    # dataset content.
    override_manifest = dict(manifest)
    override_manifest["thresholds"] = threshold_config
    validate_manifest(override_manifest, field_blocks=field_blocks)

    overall = MetricAccumulator()
    documents = {name: MetricAccumulator() for name in document_types}
    slices: dict[str, dict[str, MetricAccumulator]] = defaultdict(
        lambda: defaultdict(MetricAccumulator)
    )
    document_slices: dict[
        str, dict[str, dict[str, MetricAccumulator]]
    ] = {
        name: defaultdict(lambda: defaultdict(MetricAccumulator))
        for name in document_types
    }
    sample_reports: list[dict[str, Any]] = []

    for sample in manifest["samples"]:
        asset_path = root / sample["asset"]
        if not asset_path.is_file():
            raise ManifestError(
                f"sample {sample['id']} asset does not exist: {asset_path}"
            )

        try:
            raw_result = scanner(str(asset_path))
            observation = _compare(
                sample,
                raw_result,
                runtime_error=False,
                field_blocks=field_blocks,
            )
        except Exception:  # benchmark must record, not hide, scanner failures
            observation = _compare(
                sample,
                {"status": "failure", "documentType": "unknown"},
                runtime_error=True,
                field_blocks=field_blocks,
            )
        document_type = sample["documentType"]
        overall.add(observation, field_prefix=f"{document_type}.")
        documents[document_type].add(observation)

        for dimension, values in _sample_slice_values(sample).items():
            for value in values:
                slices[dimension][value].add(
                    observation, field_prefix=f"{document_type}."
                )
                document_slices[document_type][dimension][value].add(observation)

        sample_reports.append(
            {
                "id": observation.sample_id,
                "expectedDocumentType": observation.expected_document_type,
                "actualDocumentType": observation.actual_document_type,
                "classificationCorrect": observation.classification_correct,
                "expectedAccepted": observation.expected_accepted,
                "actualAccepted": observation.actual_accepted,
                "falseSuccess": observation.false_success,
                "falseRejection": observation.false_rejection,
                "runtimeError": observation.runtime_error,
                "completeRecordExact": observation.complete_record_exact,
                "completeRecordNormalized": (
                    observation.complete_record_normalized
                ),
                "fields": {
                    name: {
                        "present": outcome.present,
                        "exact": outcome.exact,
                        "normalized": outcome.normalized,
                    }
                    for name, outcome in sorted(
                        observation.field_outcomes.items()
                    )
                },
            }
        )

    summary_metrics = overall.to_dict()
    document_metrics = {
        name: accumulator.to_dict()
        for name, accumulator in documents.items()
    }
    slice_metrics = {
        dimension: {
            value: accumulator.to_dict()
            for value, accumulator in sorted(values.items())
        }
        for dimension, values in sorted(slices.items())
    }
    document_slice_metrics = {
        document_type: {
            dimension: {
                value: accumulator.to_dict()
                for value, accumulator in sorted(values.items())
            }
            for dimension, values in sorted(dimensions.items())
        }
        for document_type, dimensions in document_slices.items()
    }

    checks = _threshold_checks(
        summary_metrics,
        threshold_config["overall"],
        "overall",
    )

    per_document = threshold_config.get("perDocument", {})
    common_document_rules = per_document.get("*", {})
    for document_type in document_types:
        rules = dict(common_document_rules)
        rules.update(per_document.get(document_type, {}))
        checks.extend(
            _threshold_checks(
                document_metrics[document_type],
                rules,
                f"document:{document_type}",
            )
        )

    per_slice = threshold_config.get("perSlice")
    if per_slice is not None:
        for dimension in per_slice["dimensions"]:
            for value, metrics in slice_metrics[dimension].items():
                sample_count_passed = metrics["samples"] >= per_slice[
                    "minimumSamples"
                ]
                checks.append(
                    {
                        "scope": f"slice:{dimension}={value}",
                        "rule": "minimumSamples",
                        "metric": "samples",
                        "actual": metrics["samples"],
                        "threshold": per_slice["minimumSamples"],
                        "operator": ">=",
                        "passed": sample_count_passed,
                    }
                )
                checks.extend(
                    _threshold_checks(
                        metrics,
                        per_slice.get("rules", {}),
                        f"slice:{dimension}={value}",
                    )
                )
        for document_type, dimensions in document_slice_metrics.items():
            for dimension in per_slice["dimensions"]:
                for value, metrics in dimensions[dimension].items():
                    scope = (
                        f"document-slice:{document_type}:"
                        f"{dimension}={value}"
                    )
                    checks.append(
                        {
                            "scope": scope,
                            "rule": "minimumSamples",
                            "metric": "samples",
                            "actual": metrics["samples"],
                            "threshold": per_slice["minimumSamples"],
                            "operator": ">=",
                            "passed": (
                                metrics["samples"]
                                >= per_slice["minimumSamples"]
                            ),
                        }
                    )
                    checks.extend(
                        _threshold_checks(
                            metrics,
                            per_slice.get("rules", {}),
                            scope,
                        )
                    )

    # Runtime exceptions are never allowed to pass merely because an override
    # omitted maxRuntimeErrorRate at a narrower scope.
    if summary_metrics["runtimeErrors"]:
        checks.append(
            {
                "scope": "overall",
                "rule": "noRuntimeErrors",
                "metric": "runtimeErrors",
                "actual": summary_metrics["runtimeErrors"],
                "threshold": 0,
                "operator": "==",
                "passed": False,
            }
        )

    failures = [check for check in checks if not check["passed"]]
    return {
        "reportSchemaVersion": REPORT_SCHEMA_VERSION,
        "manifestSchemaVersion": manifest["schemaVersion"],
        "datasetVersion": manifest["datasetVersion"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fieldBlocks": dict(field_blocks),
        "passed": not failures,
        "summary": summary_metrics,
        "documents": document_metrics,
        "slices": slice_metrics,
        "documentSlices": document_slice_metrics,
        "checks": checks,
        "failures": failures,
        "samples": sample_reports,
    }


def _load_threshold_override(path: str | Path) -> dict[str, Any]:
    threshold_path = Path(path)
    try:
        loaded = json.loads(threshold_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(
            f"Could not load thresholds {threshold_path}: {exc}"
        ) from exc
    _expect_type(loaded, Mapping, "threshold override")
    return dict(loaded)


def _write_report(report: Mapping[str, Any], path: str | Path) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate private non-passport KYC OCR fixtures."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Asset root; defaults to the manifest directory.",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        help="Optional JSON threshold configuration replacing manifest thresholds.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report here; otherwise print it to stdout.",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        threshold_override = (
            _load_threshold_override(args.thresholds)
            if args.thresholds
            else None
        )
        from core.pipeline import scan

        report = evaluate_manifest(
            manifest,
            scan,
            dataset_root=args.dataset_root or args.manifest.parent,
            thresholds=threshold_override,
        )
    except (ImportError, ManifestError, OSError, TypeError, ValueError) as exc:
        print(f"KYC benchmark error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        _write_report(report, args.output)
        print(f"Wrote KYC benchmark report to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
