#!/usr/bin/env python3
"""
Generate clean, synthetic, labelled Indian PAN-card specimen images.

Produces three fictitious PAN cards spanning the two common layouts the
extractor must handle:

  * pan_01 — e-PAN style: "Label : value" on the same row (value to the right).
  * pan_02 — NSDL laminated style: value printed *below* its label.
  * pan_03 — e-PAN style again, with a different identity and label spellings
    ("Name of the Cardholder", "DOB").

Each card carries the routing keywords the document classifier needs
("INCOME TAX DEPARTMENT" + "PERMANENT ACCOUNT NUMBER") and a holder-type-valid
PAN (5 letters + 4 digits + a holder-type letter, here 'P' for individual),
rendered in a monospace font so RapidOCR reads it cleanly.

All identities are fictitious — nothing here is real PII.

A `manifest.json` is written via `synth_common.write_manifest` describing each
image and its ground-truth fields (camelCase keys matching the `panFields`
JSON block: panNumber, name, fatherName, dateOfBirth).

Usage:
    uv run python scripts/generate_synthetic_pan.py [--verify]

With `--verify`, each rendered clean image is scanned through the *real*
pipeline (`core.pipeline.scan`) and checked for correct routing
(documentType == 'pan') and exact per-field extraction against ground truth.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from synth_common import Card, LabelledImage, write_manifest, REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Specimen identities (all fictitious). Names deliberately avoid words that the
# extractor's label heuristics treat as field-label hints (NAME / DATE / BIRTH /
# FATHER / PARENT), so the value regions are never discarded as "looks like a
# label".
# ---------------------------------------------------------------------------

SPECIMENS = [
    {
        "out": "pan_01.png",
        "layout": "right",
        "pan": "ABCPE1234F",
        "name": "ROHIT KUMAR SHARMA",
        "father": "MAHESH SHARMA",
        "dob": "14/08/1991",
        "name_label": "Name",
        "father_label": "Father's Name",
        "dob_label": "Date of Birth",
    },
    {
        "out": "pan_02.png",
        "layout": "below",
        "pan": "FGHPK7821L",
        "name": "PRIYA VERMA",
        "father": "SURESH VERMA",
        "dob": "02/03/1988",
        "name_label": "Name",
        "father_label": "Father's Name",
        "dob_label": "Date of Birth",
    },
    {
        "out": "pan_03.png",
        "layout": "right",
        "pan": "LMNPS4567P",
        "name": "ARJUN SINGH RATHORE",
        "father": "VIKRAM SINGH RATHORE",
        "dob": "27/11/1979",
        "name_label": "Name of the Cardholder",
        "father_label": "Father's Name",
        "dob_label": "DOB",
    },
]


def render(spec: dict, out_path: Path) -> None:
    """Render one PAN specimen card to ``out_path``."""
    card = Card(width=1000, height=640)

    # --- Government header band (routing keywords live here) ---
    card.header(40, 28, "INCOME TAX DEPARTMENT", size=30)
    card.text(40, 70, "GOVT. OF INDIA", style="sans", size=22, fill=(90, 90, 90))
    card.header(560, 40, "PERMANENT ACCOUNT NUMBER", size=22)
    card.text(560, 72, "CARD", style="sans", size=20, fill=(90, 90, 90))
    card.line(40, 108, 960, 108, width=2)

    # --- Photo placeholder (OCR ignores it). Placed in the lower-right corner,
    # clear of the value column so it never overlaps text. ---
    card.photo_box(810, 470, 150, 150)

    if spec["layout"] == "right":
        # e-PAN style: "Label : value" on the same row, value to the right.
        #
        # RapidOCR merges a label and its value into ONE region when they sit on
        # the same row only a small gap apart (e.g. "Father's NameMAHESH ...").
        # That destroys same-row extraction because there is then no separate
        # value region to the right of the label. To keep them as distinct
        # regions we place every value at a fixed left edge far from the labels
        # (a wide gutter), which the detector resolves as two separate boxes.
        value_x = 520
        rows = [
            ("Permanent Account Number", spec["pan"], 34, "mono"),
            (spec["name_label"], spec["name"], 30, "sans"),
            (spec["father_label"], spec["father"], 30, "sans"),
            (spec["dob_label"], spec["dob"], 30, "mono"),
        ]
        y = 140
        for label, value, vsize, vstyle in rows:
            card.text(40, y + 4, label, style="sans", size=22, fill=(90, 90, 90))
            card.text(value_x, y, value, style=vstyle, size=vsize, fill=(0, 0, 0))
            y += 80
    else:
        # NSDL laminated style: value printed *below* its label.
        card.field_row(
            40, 140, "Permanent Account Number", spec["pan"],
            mode="below", label_size=22, value_size=36, value_style="mono",
        )
        y = 240
        y = card.field_row(
            40, y, spec["name_label"], spec["name"],
            mode="below", label_size=22, value_size=32, value_style="sans",
        )
        y += 18
        y = card.field_row(
            40, y, spec["father_label"], spec["father"],
            mode="below", label_size=22, value_size=32, value_style="sans",
        )
        y += 18
        y = card.field_row(
            40, y, spec["dob_label"], spec["dob"],
            mode="below", label_size=22, value_size=32, value_style="mono",
        )

    card.save(out_path)


def build_manifest_item(spec: dict) -> LabelledImage:
    rel = f"sample-documents/pan/{spec['out']}"
    return LabelledImage(
        file=rel,
        document_type="pan",
        fields={
            "panNumber": spec["pan"],
            "name": spec["name"],
            "fatherName": spec["father"],
            "dateOfBirth": spec["dob"],
        },
    )


# Map ground-truth manifest keys to the extracted panFields keys.
_FIELD_KEYS = ["panNumber", "name", "fatherName", "dateOfBirth"]


def verify_image(image_path: Path, fields: dict) -> tuple[bool, dict]:
    """Scan one rendered image through the real pipeline and compare to truth.

    Returns (ok, per_field_report) where per_field_report maps each ground-truth
    key to {"expected", "got", "ok"} and ``ok`` is True iff routing succeeded and
    every ground-truth field matched exactly.
    """
    from core.pipeline import scan

    d = scan(str(image_path)).to_dict()
    routed = d.get("documentType") == "pan"
    block = d.get("panFields") or {}

    report: dict = {"documentType": d.get("documentType"), "fields": {}}
    all_fields_ok = True
    for key in _FIELD_KEYS:
        if key not in fields:
            continue
        expected = fields[key]
        got = block.get(key)
        ok = got == expected
        all_fields_ok = all_fields_ok and ok
        report["fields"][key] = {"expected": expected, "got": got, "ok": ok}

    return (routed and all_fields_ok), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Scan each rendered image through the real pipeline and check readback.",
    )
    args = parser.parse_args()

    out_dir = REPO_ROOT / "sample-documents" / "pan"
    items: list[LabelledImage] = []
    rendered: list[tuple[dict, Path]] = []

    for spec in SPECIMENS:
        out_path = out_dir / spec["out"]
        render(spec, out_path)
        items.append(build_manifest_item(spec))
        rendered.append((spec, out_path))
        print(f"Rendered {out_path}")

    manifest_path = write_manifest("pan", items)
    print(f"Wrote manifest → {manifest_path}")

    if not args.verify:
        return 0

    print("\nVerifying readback through the real pipeline...\n")
    all_ok = True
    for spec, out_path in rendered:
        truth = build_manifest_item(spec).fields
        ok, report = verify_image(out_path, truth)
        all_ok = all_ok and ok
        print(f"=== {spec['out']} ===")
        print(f"  documentType: {report['documentType']}  (expected 'pan')")
        for key, info in report["fields"].items():
            mark = "OK " if info["ok"] else "FAIL"
            print(f"  [{mark}] {key}: expected={info['expected']!r} got={info['got']!r}")
        print(f"  -> {'PASS' if ok else 'FAIL'}\n")

    print(f"Overall: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
