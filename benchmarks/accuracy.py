"""
Accuracy benchmark for passport OCR pipeline.

Runs the pipeline against all images in sample-passports/ and reports metrics.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import scan


def run_benchmark():
    sample_dir = Path(__file__).parent.parent / "sample-passports"
    images = list(sample_dir.glob("*.jpg")) + list(sample_dir.glob("*.png"))

    if not images:
        print("No sample images found in sample-passports/")
        sys.exit(1)

    print(f"Running benchmark on {len(images)} images...\n")

    results = []
    total_start = time.monotonic()

    for image_path in sorted(images):
        print(f"  Processing: {image_path.name}")
        result = scan(str(image_path))
        results.append((image_path.name, result))

        status = "OK" if result.success else "FAIL"
        print(f"    {status} | confidence={result.confidence:.3f} | "
              f"mrz_valid={result.mrz_valid} | {result.processing_ms}ms")

        if result.errors:
            print(f"    errors: {result.errors}")
        if result.warnings:
            print(f"    warnings: {result.warnings}")
        print()

    total_ms = int((time.monotonic() - total_start) * 1000)

    # Summary
    successful = [r for _, r in results if r.success]
    mrz_valid = [r for _, r in results if r.mrz_valid]
    avg_conf = sum(r.confidence for _, r in results) / len(results) if results else 0
    avg_time = sum(r.processing_ms for _, r in results) / len(results) if results else 0

    print("=" * 60)
    print(f"Total images:      {len(results)}")
    print(f"Successful:        {len(successful)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"MRZ valid:         {len(mrz_valid)} ({len(mrz_valid)/len(results)*100:.1f}%)")
    print(f"Avg confidence:    {avg_conf:.3f}")
    print(f"Avg processing:    {avg_time:.0f}ms")
    print(f"Total time:        {total_ms}ms")
    print("=" * 60)

    # Exit with failure if accuracy is below threshold
    success_rate = len(successful) / len(results) if results else 0
    if success_rate < 0.95:
        print(f"\nFAIL: Success rate {success_rate:.1%} is below 95% threshold")
        sys.exit(1)


if __name__ == "__main__":
    run_benchmark()
