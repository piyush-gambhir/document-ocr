"""Private passport OCR benchmark with fail-closed release gates.

The ignored dataset contains a manifest.json keyed by opaque asset filename.
Reports contain aggregate metrics only, never extracted fields or OCR errors.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

STATUS_MATCH_TARGET = 0.95
FIELD_ACCURACY_TARGET = 0.97
MRZ_EXACT_TARGET = 0.99
NON_BIODATA_TARGET = 0.95
WARM_BIODATA_MEDIAN_MS_TARGET = 5000
FIELD_BLOCKS = ("fields", "backPageFields")


def _ratio(matches: int, total: int) -> float | None:
    return matches / total if total else None


def _score_fields(
    actual_fields: Mapping[str, Any] | None,
    expected_fields: Mapping[str, Any] | None,
) -> tuple[int, int]:
    if not expected_fields:
        return 0, 0
    actual_fields = actual_fields if isinstance(actual_fields, Mapping) else {}
    return (
        sum(actual_fields.get(key) == value for key, value in expected_fields.items()),
        len(expected_fields),
    )


def evaluate_results(
    results: Sequence[tuple[Mapping[str, Any], Mapping[str, Any] | None]],
) -> dict[str, Any]:
    """Score (expected, actual) pairs; a missing actual records a scanner crash.

    Missing measurement denominators fail the corresponding release gate.
    Field and MRZ scores require the expected status/document/page routing.
    Additional annotated result metadata, including unsupportedReason and
    mrzValid, participates in the status/metadata match gate.
    """
    status_matches = field_matches = field_total = mrz_matches = mrz_total = 0
    back_matches = back_total = runtime_errors = 0
    biodata_total = 0
    biodata_latencies: list[float] = []

    for expected, actual in results:
        runtime_errors += int(actual is None)
        actual = actual or {}
        metadata = {
            "documentType": "passport",
            **{
                key: value
                for key, value in expected.items()
                if key not in (*FIELD_BLOCKS, "mrzRaw")
            },
        }
        matched = all(actual.get(key) == value for key, value in metadata.items())
        status_matches += int(matched)
        for block in FIELD_BLOCKS:
            matches, total = _score_fields(actual.get(block), expected.get(block))
            field_matches += matches if matched else 0
            field_total += total

        if expected.get("mrzRaw") is not None:
            mrz_total += 1
            mrz_matches += int(matched and actual.get("mrzRaw") == expected["mrzRaw"])

        if (
            expected.get("status") == "success"
            and expected.get("pageType") == "passport_non_biodata"
        ):
            back_total += 1
            back_matches += int(matched)

        if (
            expected.get("status") == "success"
            and expected.get("pageType") == "passport_biodata"
        ):
            biodata_total += 1
            latency = actual.get("processingMs")
            if (
                not isinstance(latency, bool)
                and isinstance(latency, (int, float))
                and math.isfinite(latency)
                and latency > 0
            ):
                biodata_latencies.append(latency)

    metrics = {
        "samples": len(results),
        "statusMatches": status_matches,
        "statusMatchRate": _ratio(status_matches, len(results)),
        "fieldMatches": field_matches,
        "fieldExpectations": field_total,
        "fieldAccuracy": _ratio(field_matches, field_total),
        "mrzMatches": mrz_matches,
        "mrzExpectations": mrz_total,
        "mrzExactRate": _ratio(mrz_matches, mrz_total),
        "nonBiodataMatches": back_matches,
        "nonBiodataExpectations": back_total,
        "nonBiodataAccuracy": _ratio(back_matches, back_total),
        "runtimeErrors": runtime_errors,
        "biodataSamples": biodata_total,
        "biodataLatencySamples": len(biodata_latencies),
        "warmBiodataMedianMs": (
            statistics.median(biodata_latencies) if biodata_latencies else None
        ),
    }
    gates = (
        ("statusMatchRate", STATUS_MATCH_TARGET, ">="),
        ("fieldAccuracy", FIELD_ACCURACY_TARGET, ">="),
        ("mrzExactRate", MRZ_EXACT_TARGET, ">="),
        ("nonBiodataAccuracy", NON_BIODATA_TARGET, ">="),
        ("warmBiodataMedianMs", WARM_BIODATA_MEDIAN_MS_TARGET, "<="),
        ("runtimeErrors", 0, "<="),
    )
    checks = []
    for metric, threshold, operator in gates:
        actual = metrics[metric]
        passed = actual is not None and (
            actual >= threshold if operator == ">=" else actual <= threshold
        )
        checks.append({
            "metric": metric,
            "actual": actual,
            "threshold": threshold,
            "operator": operator,
            "passed": passed,
        })
    checks.append({
        "metric": "biodataLatencySamples",
        "actual": len(biodata_latencies),
        "threshold": biodata_total,
        "operator": "==",
        "passed": biodata_total > 0 and len(biodata_latencies) == biodata_total,
    })
    failures = [check for check in checks if not check["passed"]]
    return {"passed": not failures, "metrics": metrics, "checks": checks, "failures": failures}


def _load_dataset(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    expectations = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(expectations, dict) or not expectations:
        raise ValueError("manifest must be a non-empty mapping of assets to expectations")
    cases = []
    for name, expected in expectations.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("manifest asset names must be non-empty strings")
        asset = (root / name).resolve()
        if not asset.is_relative_to(root.resolve()) or not asset.is_file():
            raise ValueError("manifest assets must exist inside the dataset root")
        if not isinstance(expected, dict) or not all(
            isinstance(expected.get(key), str) and expected[key]
            for key in ("status", "pageType")
        ):
            raise ValueError("every sample needs string status and pageType expectations")
        for block in FIELD_BLOCKS:
            if expected.get(block) is not None and not isinstance(expected[block], dict):
                raise ValueError(f"{block} expectations must be objects or null")
        if expected.get("mrzRaw") is not None and (
            not isinstance(expected["mrzRaw"], list)
            or len(expected["mrzRaw"]) != 2
            or not all(isinstance(line, str) and line for line in expected["mrzRaw"])
        ):
            raise ValueError("mrzRaw expectations must contain two non-empty strings")
        cases.append((asset, expected))
    return cases


def run_benchmark(
    dataset_root: str | Path | None = None,
    scanner: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    root = Path(dataset_root or os.getenv(
        "DOCUMENT_OCR_BENCHMARK_DATA", Path(__file__).resolve().parent.parent / "benchmark-data"
    ))
    cases = _load_dataset(root)
    if scanner is None:
        # Delay OCR imports until a valid private dataset is available.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from core.pipeline import scan

        scanner = scan

    warmup = next((asset for asset, expected in cases if (
        expected["status"] == "success" and expected["pageType"] == "passport_biodata"
    )), None)
    if warmup is not None:
        scanner(str(warmup))

    results = []
    for asset, expected in cases:
        try:
            result = scanner(str(asset))
            actual = result if isinstance(result, Mapping) else result.to_dict()
            if not isinstance(actual, Mapping):
                raise TypeError("scanner must return a mapping or a result with to_dict()")
        except Exception:  # Count failures without leaking OCR text or identity fields.
            actual = None
        results.append((expected, actual))
    return evaluate_results(results)


def main() -> int:
    try:
        report = run_benchmark()
    except Exception as exc:
        # Runtime messages may contain identity values; expose only the error type.
        print(f"Passport benchmark setup failed ({type(exc).__name__}). Check the dataset and OCR setup.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
