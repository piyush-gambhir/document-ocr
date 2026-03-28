"""
Accuracy benchmark for passport OCR pipeline.

Runs the pipeline against all images in sample-passports/ and reports metrics.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import scan

STATUS_MATCH_TARGET = 0.95
FIELD_ACCURACY_TARGET = 0.97
MRZ_EXACT_TARGET = 0.99
NON_BIODATA_TARGET = 0.95
WARM_BIODATA_MEDIAN_MS_TARGET = 5000


def run_benchmark():
    sample_dir = Path(__file__).parent.parent / "sample-passports"
    manifest_path = sample_dir / "manifest.json"
    expectations = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    images = [sample_dir / name for name in expectations]

    if not images:
        print("No sample images found in sample-passports/")
        sys.exit(1)

    warmup_image = next(
        (
            sample_dir / name
            for name, expected in expectations.items()
            if expected.get("status") == "success" and expected.get("pageType") == "passport_biodata"
        ),
        None,
    )

    if warmup_image is not None:
        print(f"Warming OCR pipeline with {warmup_image.name}...\n")
        scan(str(warmup_image))

    print(f"Running benchmark on {len(images)} images...\n")

    results = []
    total_start = time.monotonic()

    for image_path in images:
        print(f"  Processing: {image_path.name}")
        result = scan(str(image_path))
        expected = expectations.get(image_path.name, {})
        matched = (
            result.status == expected.get("status")
            and result.document_type == expected.get("documentType", result.document_type)
            and result.page_type == expected.get("pageType")
        )
        field_matches, field_total = _score_fields(result.to_dict().get("fields"), expected.get("fields"))
        mrz_exact = _score_mrz(result.mrz_raw, expected.get("mrzRaw"))
        unsupported_reason_match = _score_unsupported_reason(result.unsupported_reason, expected.get("unsupportedReason"))
        results.append((image_path.name, result, matched))

        status = "OK" if matched else "FAIL"
        print(f"    {status} | status={result.status} | page_type={result.page_type} | "
              f"confidence={result.confidence:.3f} | {result.processing_ms}ms")

        if field_total:
            print(f"    fields: {field_matches}/{field_total} exact")
        if mrz_exact is not None:
            print(f"    mrz_exact: {mrz_exact}")
        if unsupported_reason_match is not None:
            print(f"    unsupported_reason: {unsupported_reason_match}")

        if result.errors:
            print(f"    errors: {result.errors}")
        if result.warnings:
            print(f"    warnings: {result.warnings}")
        print()

    total_ms = int((time.monotonic() - total_start) * 1000)

    # Summary
    matched_results = [matched for _, _, matched in results]
    supported_success = [r for _, r, matched in results if matched and r.status == "success"]
    correctly_rejected = [r for _, r, matched in results if matched and r.status == "unsupported_page"]
    avg_conf = sum(r.confidence for _, r, _ in results) / len(results) if results else 0
    avg_time = sum(r.processing_ms for _, r, _ in results) / len(results) if results else 0
    biodata_latencies = [
        r.processing_ms
        for name, r, _ in results
        if expectations.get(name, {}).get("status") == "success"
        and expectations.get(name, {}).get("pageType") == "passport_biodata"
    ]
    warm_biodata_median = statistics.median(biodata_latencies) if biodata_latencies else 0

    total_field_matches = 0
    total_field_expectations = 0
    mrz_exact_matches = 0
    mrz_expectations = 0
    non_biodata_matches = 0
    non_biodata_expectations = 0

    for name, result, _ in results:
        expected = expectations.get(name, {})

        field_matches, field_total = _score_fields(result.to_dict().get("fields"), expected.get("fields"))
        total_field_matches += field_matches
        total_field_expectations += field_total

        mrz_exact = _score_mrz(result.mrz_raw, expected.get("mrzRaw"))
        if mrz_exact is not None:
            mrz_expectations += 1
            mrz_exact_matches += int(mrz_exact)

        if expected.get("status") == "unsupported_page" and expected.get("pageType") == "passport_non_biodata":
            non_biodata_expectations += 1
            non_biodata_matches += int(
                result.status == "unsupported_page"
                and result.page_type == "passport_non_biodata"
                and result.unsupported_reason == expected.get("unsupportedReason")
            )

    field_accuracy = (
        total_field_matches / total_field_expectations
        if total_field_expectations
        else 1.0
    )
    mrz_exact_rate = (mrz_exact_matches / mrz_expectations) if mrz_expectations else 1.0
    non_biodata_rate = (non_biodata_matches / non_biodata_expectations) if non_biodata_expectations else 1.0

    print("=" * 60)
    print(f"Total images:      {len(results)}")
    print(f"Status matched:    {sum(matched_results)} ({sum(matched_results)/len(results)*100:.1f}%)")
    print(f"Successful:        {len(supported_success)}")
    print(f"Correctly rejected:{len(correctly_rejected)}")
    print(f"Field accuracy:    {field_accuracy:.1%}")
    print(f"MRZ exact-match:   {mrz_exact_rate:.1%}")
    print(f"Non-biodata acc:   {non_biodata_rate:.1%}")
    print(f"Warm biodata p50:  {warm_biodata_median:.0f}ms")
    print(f"Avg confidence:    {avg_conf:.3f}")
    print(f"Avg processing:    {avg_time:.0f}ms")
    print(f"Total time:        {total_ms}ms")
    print("=" * 60)

    matched_rate = sum(matched_results) / len(results) if results else 0
    failures = []
    if matched_rate < STATUS_MATCH_TARGET:
        failures.append(
            f"Status match rate {matched_rate:.1%} is below {STATUS_MATCH_TARGET:.0%}"
        )
    if field_accuracy < FIELD_ACCURACY_TARGET:
        failures.append(
            f"Field accuracy {field_accuracy:.1%} is below {FIELD_ACCURACY_TARGET:.0%}"
        )
    if mrz_exact_rate < MRZ_EXACT_TARGET:
        failures.append(
            f"MRZ exact-match rate {mrz_exact_rate:.1%} is below {MRZ_EXACT_TARGET:.0%}"
        )
    if non_biodata_rate < NON_BIODATA_TARGET:
        failures.append(
            f"Non-biodata accuracy {non_biodata_rate:.1%} is below {NON_BIODATA_TARGET:.0%}"
        )
    if biodata_latencies and warm_biodata_median > WARM_BIODATA_MEDIAN_MS_TARGET:
        failures.append(
            f"Warm biodata median {warm_biodata_median:.0f}ms exceeds {WARM_BIODATA_MEDIAN_MS_TARGET}ms"
        )

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)


def _score_fields(actual_fields: dict | None, expected_fields: dict | None) -> tuple[int, int]:
    if not expected_fields:
        return 0, 0

    actual_fields = actual_fields or {}
    matches = 0
    total = 0
    for key, expected in expected_fields.items():
        total += 1
        matches += int(actual_fields.get(key) == expected)
    return matches, total


def _score_mrz(actual_mrz: tuple[str, str] | None, expected_mrz: list[str] | None) -> bool | None:
    if not expected_mrz:
        return None
    return list(actual_mrz) == expected_mrz if actual_mrz else False


def _score_unsupported_reason(actual_reason: str | None, expected_reason: str | None) -> bool | None:
    if expected_reason is None:
        return None
    return actual_reason == expected_reason


if __name__ == "__main__":
    run_benchmark()
