"""
End-to-end accuracy benchmark for the KYC document extractors.

Unlike the per-extractor unit tests (which feed hand-written TextRegion
fixtures), this runs the WHOLE pipeline on real rendered images:

    labelled image  ->  degradation variant  ->  core.pipeline.scan()
                    ->  documentType routing + extracted field block
                    ->  scored against the ground-truth manifest.

Dataset: synthetic, labelled specimens under sample-documents/<doc>/ (generated
by scripts/generate_synthetic_<doc>.py). Each clean image is also run through a
fixed set of degradations (blur / rotate / noise / JPEG / low-res) so the
accuracy number reflects robustness, not just pristine renders.

Run:  uv run python benchmarks/document_accuracy.py [--variants clean,blur,...]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import synth_common as sc  # noqa: E402
from core.pipeline import scan  # noqa: E402
from PIL import Image  # noqa: E402

# documentType -> the result key that holds its extracted fields
_BLOCK_KEY = {
    "pan": "panFields",
    "aadhaar": "aadhaarFields",
    "driving_licence": "drivingLicenceFields",
    "voter_id": "voterIdFields",
}

# Gate: the clean variant must hit these. Degraded variants are reported only.
CLEAN_ROUTING_TARGET = 1.0
CLEAN_FIELD_TARGET = 0.98


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(text).upper()).strip()


def _field_match(key: str, expected, actual) -> bool:
    if isinstance(expected, bool):
        return bool(actual) == expected
    if actual is None:
        return False
    e, a = _norm(expected), _norm(actual)
    if not e:
        return a == ""
    if e == a:
        return True
    # Free-text address fields reflow under OCR — accept a high fuzzy overlap.
    if "address" in key.lower():
        return fuzz.token_set_ratio(e, a) >= 85
    return False


def _scan_variant(image: Image.Image, variant: str):
    """Apply a degradation and run the pipeline; never raises."""
    try:
        degraded = sc.degrade(image, variant)
        result = scan(sc.to_png_bytes(degraded))
        return result.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        return {"documentType": "error", "_error": str(exc)}


def run(variants: list[str]) -> int:
    items = sc.load_all_manifests()
    if not items:
        print("No labelled images found under sample-documents/*/manifest.json")
        return 1

    print(f"Loaded {len(items)} labelled images across "
          f"{len({i.document_type for i in items})} document types.")
    print(f"Variants: {', '.join(variants)}\n")

    # Warm the OCR models once.
    print("Warming OCR pipeline...\n")
    first = REPO_ROOT / items[0].file
    scan(sc.to_png_bytes(Image.open(first).convert("RGB")))

    # Accumulators: (scope) -> [routed_correct, total_images, fields_matched, fields_total]
    by_variant: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0, 0])
    by_doc: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0, 0])
    by_variant_doc: dict[tuple, list[float]] = defaultdict(lambda: [0, 0, 0, 0])

    for item in items:
        img = Image.open(REPO_ROOT / item.file).convert("RGB")
        block_key = _BLOCK_KEY[item.document_type]
        print(f"  {item.file}  (expect {item.document_type}, {len(item.fields)} fields)")

        for variant in variants:
            d = _scan_variant(img, variant)
            routed = int(d.get("documentType") == item.document_type)
            block = d.get(block_key) or {}
            matched = sum(_field_match(k, v, block.get(k)) for k, v in item.fields.items())
            total = len(item.fields)

            for acc in (by_variant[variant], by_doc[item.document_type],
                        by_variant_doc[(variant, item.document_type)]):
                acc[0] += routed
                acc[1] += 1
                acc[2] += matched
                acc[3] += total

            flag = "ok " if routed and matched == total else "   "
            got = d.get("documentType")
            print(f"    {flag}{variant:9s} routed={'Y' if routed else 'N'}({got:>14s})"
                  f"  fields={matched}/{total}")
        print()

    def _line(label, acc):
        routed_pct = acc[0] / acc[1] * 100 if acc[1] else 0
        field_pct = acc[2] / acc[3] * 100 if acc[3] else 0
        return f"  {label:26s} routing={routed_pct:5.1f}%  fields={field_pct:5.1f}%  ({acc[2]}/{acc[3]})"

    print("=" * 64)
    print("BY DOCUMENT TYPE (all variants)")
    for doc in sorted(by_doc):
        print(_line(doc, by_doc[doc]))

    print("\nBY VARIANT (all documents)")
    for variant in variants:
        print(_line(variant, by_variant[variant]))

    print("\nBY VARIANT x DOCUMENT")
    for variant in variants:
        for doc in sorted(by_doc):
            acc = by_variant_doc.get((variant, doc))
            if acc:
                print(_line(f"{variant} / {doc}", acc))

    # Overall
    total_routed = sum(a[0] for a in by_variant.values())
    total_imgs = sum(a[1] for a in by_variant.values())
    total_matched = sum(a[2] for a in by_variant.values())
    total_fields = sum(a[3] for a in by_variant.values())
    print("\n" + "=" * 64)
    print(f"OVERALL  routing={total_routed/total_imgs*100:.1f}%  "
          f"fields={total_matched/total_fields*100:.1f}%  "
          f"({total_imgs} scans, {total_fields} field checks)")
    print("=" * 64)

    # Gate on the clean variant only (degraded is a robustness report).
    failures = []
    if "clean" in by_variant:
        c = by_variant["clean"]
        clean_routing = c[0] / c[1] if c[1] else 0
        clean_fields = c[2] / c[3] if c[3] else 0
        if clean_routing < CLEAN_ROUTING_TARGET:
            failures.append(f"clean routing {clean_routing:.1%} < {CLEAN_ROUTING_TARGET:.0%}")
        if clean_fields < CLEAN_FIELD_TARGET:
            failures.append(f"clean field accuracy {clean_fields:.1%} < {CLEAN_FIELD_TARGET:.0%}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS (clean gate met; degraded variants reported above)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        default=",".join(sc.DEGRADATIONS.keys()),
        help="comma-separated degradation variants to run",
    )
    args = parser.parse_args()
    chosen = [v.strip() for v in args.variants.split(",") if v.strip() in sc.DEGRADATIONS]
    raise SystemExit(run(chosen))
