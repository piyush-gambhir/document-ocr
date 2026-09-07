#!/usr/bin/env python3
"""Exact-field release evaluation for the eight experimental structured profiles.

Uses the existing KYC report/slice engine. Real-image accuracy is not measured
until a private, independently annotated manifest is actually evaluated.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from benchmarks import kyc_accuracy as engine
from core.document_registry import list_document_profiles

DOCUMENT_TYPES = (
    "us_driver_license", "us_state_id", "passport_card", "us_green_card",
    "us_ead", "visa", "us_i94", "us_w9",
)
FIELD_BLOCKS = {kind: "documentFields" for kind in DOCUMENT_TYPES}
PROFILES = {item["documentType"]: item for item in list_document_profiles() if item["documentType"] in DOCUMENT_TYPES}
IDENTIFIER_FIELDS = {
    "us_driver_license": ("documentNumber",), "us_state_id": ("documentNumber",),
    "passport_card": ("documentNumber",), "us_green_card": ("uscisNumber", "cardNumber"),
    "us_ead": ("uscisNumber", "cardNumber"), "visa": ("documentNumber",),
    "us_i94": ("i94Number", "passportNumber"), "us_w9": ("taxpayerId",),
}
DATE_FIELDS = frozenset({"dateOfBirth", "expiryDate", "issueDate", "residentSince", "validFrom", "admissionDate", "admitUntil"})
ManifestError = engine.ManifestError


def validate_manifest(manifest: Any) -> None:
    engine.validate_manifest(manifest, field_blocks=FIELD_BLOCKS)
    if manifest.get("split") not in ("tuning", "release"):
        raise ManifestError("split must be tuning or release")
    minimum = manifest.get("minimumIndependentGroups")
    if not isinstance(minimum, Mapping) or set(minimum) != {"positive", "negative"}:
        raise ManifestError("minimumIndependentGroups requires positive and negative counts")
    for value in minimum.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ManifestError("minimumIndependentGroups counts must be positive integers")
    gates = manifest.get("structuredThresholds")
    if not isinstance(gates, Mapping) or set(gates) != {"minIdentifierExactAccuracy", "minDateExactAccuracy"}:
        raise ManifestError("structuredThresholds requires exact identifier and date gates")
    for value in gates.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ManifestError("structuredThresholds values must be between 0 and 1")

    groups = defaultdict(lambda: {"positive": set(), "negative": set()})
    group_properties = {}
    assets = set()
    for sample in manifest["samples"]:
        kind, expected = sample["documentType"], sample["expected"]
        group = sample.get("groupId")
        if not isinstance(group, str) or not group.strip():
            raise ManifestError(f"sample {sample['id']} requires an opaque groupId")
        if sample.get("split", manifest["split"]) != manifest["split"]:
            raise ManifestError("samples from different splits cannot be evaluated together")
        group_key = (kind, group)
        if group_key in group_properties and group_properties[group_key] != expected["accepted"]:
            raise ManifestError("groupId has conflicting acceptance annotations within a document family")
        group_properties[group_key] = expected["accepted"]
        if sample["asset"] in assets:
            raise ManifestError("duplicate asset paths cannot inflate benchmark coverage")
        assets.add(sample["asset"])
        bucket = "positive" if expected["accepted"] else "negative"
        if bucket == "positive" or expected.get("classificationTarget") == "unknown":
            groups[kind][bucket].add(group)
        fields = expected["fields"]
        unknown = set(fields) - set(PROFILES[kind]["fields"])
        if unknown:
            raise ManifestError(f"sample {sample['id']} has unknown fields: {sorted(unknown)}")
        for name, value in fields.items():
            if value is not None and ((isinstance(value, str) and not value.strip()) or value == [] or value == {}):
                raise ManifestError(f"sample {sample['id']} empty field must be annotated null: {name}")
            if value is not None and name in IDENTIFIER_FIELDS[kind] and (not isinstance(value, str) or not value.strip()):
                raise ManifestError(f"sample {sample['id']} identifiers must be nonempty strings")
            if value is not None and name in DATE_FIELDS:
                if name == "admitUntil" and value == "D/S":
                    continue
                try:
                    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except ValueError:
                    raise ManifestError(f"sample {sample['id']} dates must be valid YYYY-MM-DD or admitUntil D/S") from None
        if any(fields[name] is None for name in expected["requiredFields"]):
            raise ManifestError("required fields cannot be absent")
        if expected["accepted"]:
            missing = set(PROFILES[kind]["requiredFields"]) - set(expected["requiredFields"])
            if missing:
                raise ManifestError(f"sample {sample['id']} omits core required fields: {sorted(missing)}")
    for kind in DOCUMENT_TYPES:
        for bucket in ("positive", "negative"):
            if len(groups[kind][bucket]) < minimum[bucket]:
                raise ManifestError(f"{kind} lacks independent {bucket} groups; negatives must include classificationTarget unknown")


def _exact_groups(metrics: Mapping[str, Any], kind: str | None = None) -> dict:
    output = {}
    for label in ("identifier", "date"):
        counts = []
        for key, counter in metrics["fields"].items():
            if kind is None:
                document_type, name = key.split(".", 1)
            else:
                document_type, name = kind, key
            selected = name in (IDENTIFIER_FIELDS[document_type] if label == "identifier" else DATE_FIELDS)
            if selected:
                counts.append(counter)
        expected = sum(counter["expected"] for counter in counts)
        exact = sum(counter["exactMatches"] for counter in counts)
        output[label + "FieldExpectations"] = expected
        output[label + "ExactMatches"] = exact
        output[label + "ExactAccuracy"] = exact / expected if expected else None
    return output


def evaluate_manifest(manifest: Mapping[str, Any], scanner: Callable[[str], Any], *, dataset_root: str | Path) -> dict:
    validate_manifest(manifest)
    measured = copy.deepcopy(manifest)
    absent_count = 0
    for sample in measured["samples"]:
        fields = sample["expected"]["fields"]
        absent_count += sum(value is None for value in fields.values())
        # An absent optional annotation is not a successful extraction and must
        # not inflate exact accuracy when actual fields are also missing.
        sample["expected"]["fields"] = {name: value for name, value in fields.items() if value is not None}
    report = engine.evaluate_manifest(measured, scanner, dataset_root=dataset_root, field_blocks=FIELD_BLOCKS)
    report.update({"benchmark": "structured_documents", "measurementStatus": "measured", "split": manifest["split"], "absentFieldAnnotationsExcluded": absent_count})
    report["summary"].update(_exact_groups(report["summary"]))
    for kind, metrics in report["documents"].items():
        metrics.update(_exact_groups(metrics, kind))
        samples = [item for item in manifest["samples"] if item["documentType"] == kind]
        metrics["independentPositiveGroups"] = len({item["groupId"] for item in samples if item["expected"]["accepted"]})
        metrics["independentNegativeGroups"] = len({item["groupId"] for item in samples if not item["expected"]["accepted"] and item["expected"].get("classificationTarget") == "unknown"})
    for scope, metrics in [("overall", report["summary"]), *[(f"document:{kind}", values) for kind, values in report["documents"].items()]]:
        for rule, metric in (("minIdentifierExactAccuracy", "identifierExactAccuracy"), ("minDateExactAccuracy", "dateExactAccuracy")):
            # W-9 has no date field. Every other profile must measure dates.
            if metric == "dateExactAccuracy" and scope == "document:us_w9":
                continue
            actual = metrics[metric]
            report["checks"].append({"scope": scope, "rule": rule, "metric": metric, "actual": actual, "threshold": manifest["structuredThresholds"][rule], "operator": ">=", "passed": actual is not None and actual >= manifest["structuredThresholds"][rule]})
    report["failures"] = [check for check in report["checks"] if not check["passed"]]
    report["passed"] = not report["failures"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest)
        from core.pipeline import scan
        report = evaluate_manifest(manifest, scan, dataset_root=args.dataset_root or args.manifest.parent)
    except (OSError, ValueError, TypeError, ImportError) as error:
        print(f"Structured benchmark setup error: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
