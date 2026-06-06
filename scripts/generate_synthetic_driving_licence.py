#!/usr/bin/env python3
"""
Generate clean, synthetic, labelled specimen images of the Indian Driving
Licence (DL) for the end-to-end accuracy benchmark.

Each image is rendered via the shared `synth_common.Card` helper with known
ground-truth field values, then (under ``--verify``) scanned through the *real*
OCR pipeline (`core.pipeline.scan`) and checked field-by-field against that
ground truth.

Three specimens with different identities / states / field mixes:
  * dl_01 — standard card: DL no, name, S/o, DOB, issue, single validity, address.
  * dl_02 — both NT and TR validity dates (validityDate = NT, transport = TR).
  * dl_03 — card carrying blood group + class of vehicle (LMV / MCWG).

The pipeline routes a non-passport KYC image by running full-page OCR and then
`classify_document`, which needs the "DRIVING LICENCE" keyword plus a valid DL
number token. The DL extractor assigns each date strictly by the label adjacent
to it (right-then-below), so every date is rendered immediately next to its own
label to avoid cross-assignment.

Usage:
    uv run python scripts/generate_synthetic_driving_licence.py [--verify]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from synth_common import Card, LabelledImage, REPO_ROOT, write_manifest  # noqa: E402

DOC_TYPE = "driving_licence"
OUT_DIR = REPO_ROOT / "sample-documents" / DOC_TYPE


# ---------------------------------------------------------------------------
# Specimen definitions (all identities fictitious)
#
# `fields` holds the camelCase ground-truth that the pipeline must read back.
# Only keys present here are rendered + scored for that image.
# ---------------------------------------------------------------------------

SPEC_01 = {
    "file": "sample-documents/driving_licence/dl_01.png",
    "fields": {
        "dlNumber": "MH1220110012345",
        "name": "RAJESH KUMAR SHARMA",
        "relationName": "MOHAN LAL SHARMA",
        "dateOfBirth": "14/03/1986",
        "issueDate": "09/06/2018",
        "validityDate": "13/03/2026",
        "address": "FLAT 7B GREEN PARK, ANDHERI WEST, MUMBAI 400058",
    },
}

SPEC_02 = {
    "file": "sample-documents/driving_licence/dl_02.png",
    "fields": {
        "dlNumber": "DL0420110149646",
        "name": "PRIYA SINGH",
        "relationName": "RAVINDER SINGH",
        "dateOfBirth": "22/11/1990",
        "issueDate": "05/01/2020",
        "validityDate": "21/11/2030",
        "validityDateTransport": "04/01/2023",
        "address": "112 NEHRU NAGAR, ROHINI, NEW DELHI 110085",
    },
}

SPEC_03 = {
    "file": "sample-documents/driving_licence/dl_03.png",
    "fields": {
        "dlNumber": "TN0120200001234",
        "name": "ARUN VENKATESAN",
        "relationName": "S VENKATESAN",
        "dateOfBirth": "30/07/1995",
        "issueDate": "18/02/2021",
        "validityDate": "29/07/2035",
        # The extractor emits COV tokens in canonical `_COV_TOKENS` order
        # (MCWG before LMV), so the ground truth matches that order even though
        # the card prints them "LMV, MCWG".
        "bloodGroup": "O+",
        "classOfVehicle": "MCWG, LMV",
        "address": "24 GANDHI STREET, T NAGAR, CHENNAI 600017",
    },
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _spaced_dl(dl: str) -> str:
    """Render the DL number grouped (state+RTO then serial) for legibility.

    `normalize_dl` strips non-alphanumerics, so the grouped form scans back to
    the compact ground-truth value.
    """
    return f"{dl[:4]} {dl[4:]}"


# Horizontal gap between a label and its value. Deliberately wide so RapidOCR
# emits the label and value as *separate* regions (a small gap is read as one
# merged region, e.g. "Valid Till13/03/2026") and so the value's left edge sits
# clearly to the right of the label's OCR bounding box — which is what
# `find_visual_value_right` requires to assign the date to its own label.
_LABEL_VALUE_GAP = 90


def render(spec: dict) -> Path:
    """Render one specimen DL card to PNG and return its absolute path."""
    f = spec["fields"]
    card = Card(width=1000, height=680)

    # --- Title band: routing keywords live here. ---
    card.header(40, 26, "INDIAN UNION DRIVING LICENCE", size=30)
    card.text(40, 64, "THE UNION OF INDIA  -  TRANSPORT DEPARTMENT", style="sans", size=20)
    card.line(40, 96, 960, 96, width=2)

    # Photo placeholder on the right (OCR ignores it); text column on the left.
    card.photo_box(790, 120, 160, 200)

    left_x = 40
    # The DL number is the strongest routing/format signal — render it mono,
    # grouped, near the top so it is unambiguous.
    card.field_row(
        left_x, 120, "DL No", _spaced_dl(f["dlNumber"]),
        mode="right", value_style="mono", value_size=26,
        gap=_LABEL_VALUE_GAP, line_gap=44,
    )

    y = 176
    y = card.field_row(
        left_x, y, "Name", f["name"],
        mode="right", value_size=24, gap=_LABEL_VALUE_GAP, line_gap=42,
    )
    if "relationName" in f:
        y = card.field_row(
            left_x, y, "Son/Daughter/Wife of", f["relationName"],
            mode="right", value_size=24, gap=_LABEL_VALUE_GAP, line_gap=42,
        )

    # Dates: each label immediately left of its own value on its own row, so the
    # extractor's adjacent-label assignment cannot cross-wire DOB / issue / validity.
    if "dateOfBirth" in f:
        y = card.field_row(
            left_x, y, "Date of Birth", f["dateOfBirth"],
            mode="right", value_style="mono", value_size=24,
            gap=_LABEL_VALUE_GAP, line_gap=42,
        )
    if "issueDate" in f:
        y = card.field_row(
            left_x, y, "Date of Issue", f["issueDate"],
            mode="right", value_style="mono", value_size=24,
            gap=_LABEL_VALUE_GAP, line_gap=42,
        )

    # Validity: single generic, or paired NT (primary) + TR (transport).
    if "validityDateTransport" in f:
        y = card.field_row(
            left_x, y, "Validity (NT)", f["validityDate"],
            mode="right", value_style="mono", value_size=24,
            gap=_LABEL_VALUE_GAP, line_gap=42,
        )
        y = card.field_row(
            left_x, y, "Validity (TR)", f["validityDateTransport"],
            mode="right", value_style="mono", value_size=24,
            gap=_LABEL_VALUE_GAP, line_gap=42,
        )
    elif "validityDate" in f:
        y = card.field_row(
            left_x, y, "Valid Till", f["validityDate"],
            mode="right", value_style="mono", value_size=24,
            gap=_LABEL_VALUE_GAP, line_gap=42,
        )

    # Blood group + class of vehicle on their own rows when present.
    if "bloodGroup" in f:
        y = card.field_row(
            left_x, y, "Blood Group", f["bloodGroup"],
            mode="right", value_size=24, gap=_LABEL_VALUE_GAP, line_gap=42,
        )
    if "classOfVehicle" in f:
        y = card.field_row(
            left_x, y, "Class of Vehicle", f["classOfVehicle"],
            mode="right", value_size=24, gap=_LABEL_VALUE_GAP, line_gap=42,
        )

    # Address last, as a labelled block (label on its own row, value below).
    if "address" in f:
        card.field_row(
            left_x, y, "Address", f["address"],
            mode="below", value_size=22, line_gap=40,
        )

    out_path = REPO_ROOT / spec["file"]
    card.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Verification against the real pipeline
# ---------------------------------------------------------------------------

def _verify_one(spec: dict) -> bool:
    from core.pipeline import scan  # imported lazily so --help stays fast

    image_path = REPO_ROOT / spec["file"]
    d = scan(str(image_path)).to_dict()
    doc_type = d.get("documentType")
    block = d.get("drivingLicenceFields") or {}

    print(f"\n=== {spec['file']} ===")
    print(f"  documentType = {doc_type!r}  (expected 'driving_licence')")

    ok = doc_type == "driving_licence"
    if not ok:
        print(f"  probeText = {d.get('probeText')}")

    for key, expected in spec["fields"].items():
        got = block.get(key)
        match = got == expected
        ok = ok and match
        flag = "OK " if match else "XX "
        print(f"  [{flag}] {key}: expected={expected!r} got={got!r}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Scan each rendered image through the real pipeline and check fields.",
    )
    args = parser.parse_args()

    specs = [SPEC_01, SPEC_02, SPEC_03]

    items: list[LabelledImage] = []
    for spec in specs:
        path = render(spec)
        items.append(
            LabelledImage(file=spec["file"], document_type=DOC_TYPE, fields=spec["fields"])
        )
        print(f"Rendered {path}")

    manifest_path = write_manifest(DOC_TYPE, items)
    print(f"Wrote manifest {manifest_path}")

    if args.verify:
        print("\nVerifying clean images through the real pipeline...")
        all_ok = True
        for spec in specs:
            all_ok = _verify_one(spec) and all_ok
        print(f"\nAll images clean and fields exact: {all_ok}")
        return 0 if all_ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
