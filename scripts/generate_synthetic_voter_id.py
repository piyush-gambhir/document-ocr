#!/usr/bin/env python3
"""
Generate clean, synthetic, labelled Indian Voter ID (EPIC) specimen images for
the end-to-end OCR accuracy benchmark.

Renders three EPIC cards with distinct identities and relation variants, writes
a per-document manifest, and (with --verify) scans each clean image through the
REAL pipeline to confirm it routes to documentType=='voter_id' and that every
ground-truth field reads back exactly.

All identities are fictitious.

Usage:
    uv run python scripts/generate_synthetic_voter_id.py [--verify]
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

OUT_DIR = REPO_ROOT / "sample-documents" / "voter_id"

# ---------------------------------------------------------------------------
# Specimen identities (all fictitious). Each entry carries both the render data
# and the camelCase ground-truth `fields` block the extractor must reproduce.
# ---------------------------------------------------------------------------

# Card 1: Father's Name + Sex + Date of Birth (male elector).
SPEC_01 = {
    "file": "voter_01.png",
    "epicNumber": "WBX1234567",
    "name": "RAJESH KUMAR SHARMA",
    "relationName": "MOHAN LAL SHARMA",
    "relationType": "father",
    "relationLabel": "Father's Name",
    "gender": "MALE",
    "genderDisplay": "Male",
    "dateOfBirth": "15/08/1985",
}

# Card 2: Husband's Name variant (female elector) + Sex + Date of Birth.
SPEC_02 = {
    "file": "voter_02.png",
    "epicNumber": "DLH7654321",
    "name": "PRIYA SINGH RATHORE",
    "relationName": "VIKRAM SINGH RATHORE",
    "relationType": "husband",
    "relationLabel": "Husband's Name",
    "gender": "FEMALE",
    "genderDisplay": "Female",
    "dateOfBirth": "03/12/1990",
}

# Card 3: Age instead of Date of Birth (mother's-name variant, female elector).
SPEC_03 = {
    "file": "voter_03.png",
    "epicNumber": "MHA9988776",
    "name": "ANITA DEVI VERMA",
    "relationName": "SUNITA DEVI VERMA",
    "relationType": "mother",
    "relationLabel": "Mother's Name",
    "gender": "FEMALE",
    "genderDisplay": "Female",
    "age": "34",
}

SPECS = [SPEC_01, SPEC_02, SPEC_03]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_card(spec: dict) -> Card:
    """Render one EPIC card. Layout mirrors the new-format PVC EPIC front.

    Two deliberate choices keep the real pipeline happy:

      * Label and value are rendered on *separate rows* (mode='below'). When a
        label and its value sit on the same line and close together, RapidOCR
        merges them into a single region (e.g. "Sex Male"), which defeats the
        extractor's spatial label->value resolution. Stacking them guarantees a
        distinct value region beneath each label.

      * Gender uses the "Gender" label (not "Sex") and the DOB card uses the
        "DOB" label (not "Date of Birth"). The voter extractor recognises both
        spellings, but "SEX"/"DATE OF BIRTH" are passport-biodata hints: the
        pipeline's cheap passport probe OCRs the bottom slice of the card, and
        two such hints there would mis-route the card to the passport path
        before the voter classifier ever runs. "GENDER"/"DOB" avoid that.
    """
    card = Card(width=1000, height=640)

    # --- Header band: routing keywords live here. ---
    # "Election Commission of India" + "Elector" trigger the voter_id router.
    card.header(150, 24, "ELECTION COMMISSION OF INDIA", size=30)
    card.text(
        230, 66,
        "Elector's Photo Identity Card",
        style="sans", size=22, fill=(40, 40, 40),
    )
    card.line(40, 104, 960, 104, width=2)

    # --- EPIC number, prominent, monospace (so normalize_epic reads it cleanly).
    #     Stacked label/value so OCR yields a clean standalone mono token. ---
    card.field_row(
        40, 124, "EPIC No.", spec["epicNumber"],
        mode="below", value_style="mono", value_size=30, label_size=22,
    )

    # --- Photo placeholder on the right (OCR ignores it). ---
    card.photo_box(740, 130, 200, 250)

    # --- Field block on the left. Distinct holder vs relation labels so the
    #     name never collapses into the relation. Each value is rendered below
    #     its label as a separate region. ---
    x = 40
    y = 200
    y = card.field_row(
        x, y, "Elector's Name", spec["name"],
        mode="below", value_size=26, label_size=20,
    )
    y = card.field_row(
        x, y, spec["relationLabel"], spec["relationName"],
        mode="below", value_size=26, label_size=20,
    )
    y = card.field_row(
        x, y, "Gender", spec["genderDisplay"],
        mode="below", value_size=26, label_size=20,
    )

    if "dateOfBirth" in spec:
        card.field_row(
            x, y, "DOB", spec["dateOfBirth"],
            mode="below", value_size=26, label_size=20,
        )
    else:
        card.field_row(
            x, y, "Age as on 1.1.2024", spec["age"],
            mode="below", value_size=26, label_size=20,
        )

    return card


def ground_truth_fields(spec: dict) -> dict:
    """The camelCase ground-truth block: exactly what we render."""
    fields = {
        "epicNumber": spec["epicNumber"],
        "name": spec["name"],
        "relationName": spec["relationName"],
        "relationType": spec["relationType"],
        "gender": spec["gender"],
    }
    if "dateOfBirth" in spec:
        fields["dateOfBirth"] = spec["dateOfBirth"]
    else:
        fields["age"] = spec["age"]
    return fields


def render_all() -> list[LabelledImage]:
    items: list[LabelledImage] = []
    for spec in SPECS:
        card = render_card(spec)
        out_path = OUT_DIR / spec["file"]
        card.save(out_path)
        rel = out_path.relative_to(REPO_ROOT).as_posix()
        items.append(
            LabelledImage(
                file=rel,
                document_type="voter_id",
                fields=ground_truth_fields(spec),
            )
        )
    return items


# ---------------------------------------------------------------------------
# Verification — run the REAL pipeline per clean image.
# ---------------------------------------------------------------------------

def verify(items: list[LabelledImage]) -> bool:
    from core.pipeline import scan

    all_ok = True
    for item in items:
        image_path = REPO_ROOT / item.file
        d = scan(str(image_path)).to_dict()
        doc_type = d.get("documentType")
        block = d.get("voterIdFields") or {}

        print(f"\n=== {item.file} ===")
        route_ok = doc_type == "voter_id"
        print(f"  documentType = {doc_type}  ({'OK' if route_ok else 'WRONG'})")
        if not route_ok:
            all_ok = False

        for key, expected in item.fields.items():
            got = block.get(key)
            ok = got == expected
            if not ok:
                all_ok = False
            print(f"  {key:<14} expected={expected!r:<24} got={got!r:<24} "
                  f"{'OK' if ok else 'MISMATCH'}")

    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true",
        help="Scan each rendered image through the real pipeline and check fields.",
    )
    args = parser.parse_args()

    items = render_all()
    for item in items:
        print(f"Rendered {item.file}")
    manifest_path = write_manifest("voter_id", items)
    print(f"Wrote manifest -> {manifest_path}")

    if args.verify:
        print("\nScanning rendered images through the real pipeline...")
        ok = verify(items)
        print(f"\nAll images route to voter_id and every field reads back exactly: {ok}")
        return 0 if ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
