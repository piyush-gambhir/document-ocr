#!/usr/bin/env python3
"""
Generate clean, synthetic, labelled specimen images for the Indian Aadhaar card.

Produces three specimens that exercise the real RapidOCR pipeline end-to-end:

  1. ``aadhaar_01.png`` — a front with a full Date-of-Birth line.
  2. ``aadhaar_02.png`` — a front with a Year-of-Birth line and a 16-digit VID.
  3. ``aadhaar_03.png`` — a back with the Address block and a 6-digit pincode.

Each image is rendered with the shared ``synth_common.Card`` canvas and recorded
in ``sample-documents/aadhaar/manifest.json`` with its ground-truth fields
(camelCase keys matching the ``aadhaarFields`` block the pipeline emits).

Layout notes that the Aadhaar extractor depends on (see core/aadhaar_extractor.py):
  * The holder NAME has no Latin label — it must be a prominent line directly
    ABOVE the DOB/Year-of-Birth line. We render it on its own row with a clear
    vertical gap below the "Government of India" header band so the name-above-DOB
    spatial heuristic locks onto it (and not a header/label line).
  * DOB uses a "DOB :" label and a dd/mm/yyyy date; the year-of-birth variant
    uses a "Year of Birth :" label and a bare year.
  * Gender is printed as "Male" / "Female".
  * The Aadhaar number is printed grouped "XXXX XXXX XXXX" using a Verhoeff-valid
    12-digit value (so checksumValid is True).
  * The VID is printed with a "VID :" label and grouped 4-4-4-4 across 16 digits;
    the extractor strips it before the 12-digit Aadhaar match, so it must not be
    mistaken for the Aadhaar number.
  * The back carries an "Address :" label with the address block and a pincode.

All identities are fictitious.

Usage:
    uv run python scripts/generate_synthetic_aadhaar.py [--verify]
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

from core.validators import is_valid_aadhaar  # noqa: E402

# ---------------------------------------------------------------------------
# Specimen identities (all fictitious). Aadhaar numbers are Verhoeff-valid and
# never begin with 0 or 1; verified at render time via core.validators.
# ---------------------------------------------------------------------------

AADHAAR_DIR = "sample-documents/aadhaar"

# Front #1 — full date of birth.
FRONT1 = {
    "file": f"{AADHAAR_DIR}/aadhaar_01.png",
    "name": "Ramesh Kumar Sharma",
    "dob": "15/08/1985",
    "gender_display": "Male",
    "gender": "MALE",
    "aadhaar": "9998 8877 7669",  # Verhoeff-valid
}

# Front #2 — year of birth + a 16-digit VID.
FRONT2 = {
    "file": f"{AADHAAR_DIR}/aadhaar_02.png",
    "name": "Sunita Devi Patel",
    "yob": "1990",
    "gender_display": "Female",
    "gender": "FEMALE",
    "aadhaar": "7260 1815 9082",  # Verhoeff-valid
    "vid": "9148 6541 8231 2156",
}

# Back — address block + pincode. Shares the same number space as a real card.
BACK = {
    "file": f"{AADHAAR_DIR}/aadhaar_03.png",
    "aadhaar": "5016 6131 8603",  # Verhoeff-valid
    "address_lines": [
        "S/O Mohan Lal, House No 42",
        "Gandhi Nagar, Sector 12",
        "Jaipur, Rajasthan",
    ],
    "address_gt": "S/O Mohan Lal, House No 42, Gandhi Nagar, Sector 12, Jaipur, Rajasthan - 302015",
    "pincode": "302015",
}


def _assert_valid(number: str) -> None:
    if not is_valid_aadhaar(number):
        raise SystemExit(f"FATAL: Aadhaar number {number!r} is not Verhoeff-valid")


def _header_band(card: Card) -> None:
    """Render the bilingual-ish government header band used for routing.

    Includes the classifier keywords ("Unique Identification Authority of India"
    + "AADHAAR") and the routing phrase "Government of India". Kept in the top
    band, well separated from the holder name row below.
    """
    card.header(70, 26, "Government of India", size=30)
    card.text(70, 70, "Unique Identification Authority of India", style="sans", size=22)
    card.header(70, 100, "AADHAAR", size=26)
    # Separator under the header band so the name row reads as a distinct line.
    card.line(40, 140, card.width - 40, 140, width=2)


def render_front_dob(out_path: Path) -> None:
    _assert_valid(FRONT1["aadhaar"])
    card = Card(width=1000, height=640)
    _header_band(card)

    # Photo placeholder on the left; text block to its right.
    card.photo_box(50, 175, 200, 250)

    text_x = 300
    # NAME — no Latin label, prominent, sits directly above the DOB line.
    card.text(text_x, 200, FRONT1["name"], style="sans_bold", size=34)
    # DOB line, clearly below the name.
    card.field_row(text_x, 265, "DOB :", FRONT1["dob"], value_size=28, value_style="sans")
    # Gender line below DOB.
    card.text(text_x, 310, FRONT1["gender_display"], style="sans", size=28)

    # Aadhaar number, large and grouped, near the bottom.
    card.text(text_x, 470, FRONT1["aadhaar"], style="sans_bold", size=44)

    card.save(REPO_ROOT / out_path)


def render_front_yob_vid(out_path: Path) -> None:
    _assert_valid(FRONT2["aadhaar"])
    card = Card(width=1000, height=640)
    _header_band(card)

    card.photo_box(50, 175, 200, 250)

    text_x = 300
    # NAME — prominent line directly above the Year-of-Birth line.
    card.text(text_x, 200, FRONT2["name"], style="sans_bold", size=34)
    # Year of Birth line.
    card.field_row(text_x, 265, "Year of Birth :", FRONT2["yob"], value_size=28, value_style="sans")
    # Gender line below.
    card.text(text_x, 310, FRONT2["gender_display"], style="sans", size=28)

    # VID line (16 digits, grouped 4-4-4-4) with an explicit VID label, placed
    # above the Aadhaar number so the extractor strips it first.
    card.field_row(text_x, 410, "VID :", FRONT2["vid"], value_size=30, value_style="sans")
    # Aadhaar number, grouped 4-4-4.
    card.text(text_x, 470, FRONT2["aadhaar"], style="sans_bold", size=44)

    card.save(REPO_ROOT / out_path)


def render_back(out_path: Path) -> None:
    _assert_valid(BACK["aadhaar"])
    card = Card(width=1000, height=640)

    # Back header band — keep the routing keywords present on the back too.
    card.header(70, 26, "Government of India", size=30)
    card.text(70, 70, "Unique Identification Authority of India", style="sans", size=22)
    card.header(70, 100, "AADHAAR", size=26)
    card.line(40, 140, card.width - 40, 140, width=2)

    # Address block under an "Address :" label.
    addr_x = 70
    card.text(addr_x, 180, "Address :", style="sans", size=24, fill=(90, 90, 90))
    y = 220
    for line in BACK["address_lines"]:
        card.text(addr_x, y, line, style="sans", size=26)
        y += 42
    # Pincode line (city/state already above; the 6-digit pincode on its own).
    card.text(addr_x, y, f"PIN: {BACK['pincode']}", style="sans", size=26)

    # Aadhaar number near the bottom, grouped.
    card.text(addr_x, 540, BACK["aadhaar"], style="sans_bold", size=42)

    card.save(REPO_ROOT / out_path)


def build_manifest_items() -> list[LabelledImage]:
    return [
        LabelledImage(
            file=FRONT1["file"],
            document_type="aadhaar",
            fields={
                "aadhaarNumber": FRONT1["aadhaar"],
                "name": FRONT1["name"],
                "dateOfBirth": FRONT1["dob"],
                "gender": FRONT1["gender"],
                "checksumValid": True,
            },
        ),
        LabelledImage(
            file=FRONT2["file"],
            document_type="aadhaar",
            fields={
                "aadhaarNumber": FRONT2["aadhaar"],
                "name": FRONT2["name"],
                "yearOfBirth": FRONT2["yob"],
                "gender": FRONT2["gender"],
                "checksumValid": True,
                "vid": FRONT2["vid"],
            },
        ),
        LabelledImage(
            file=BACK["file"],
            document_type="aadhaar",
            fields={
                "aadhaarNumber": BACK["aadhaar"],
                "address": BACK["address_gt"],
                "pincode": BACK["pincode"],
            },
        ),
    ]


def render_all() -> list[LabelledImage]:
    render_front_dob(Path(FRONT1["file"]))
    render_front_yob_vid(Path(FRONT2["file"]))
    render_back(Path(BACK["file"]))
    items = build_manifest_items()
    manifest_path = write_manifest("aadhaar", items)
    print(f"Rendered 3 specimen images + manifest -> {manifest_path}")
    return items


# ---------------------------------------------------------------------------
# Verification — run the REAL pipeline and compare to ground truth
# ---------------------------------------------------------------------------

# Which ground-truth keys map to which extracted aadhaarFields keys, and how to
# compare. address is compared loosely (the extractor reflows the block); the
# pincode is the load-bearing piece of the back address.
_EXACT_KEYS = {
    "aadhaarNumber": "aadhaarNumber",
    "name": "name",
    "dateOfBirth": "dateOfBirth",
    "yearOfBirth": "yearOfBirth",
    "gender": "gender",
    "pincode": "pincode",
    "checksumValid": "checksumValid",
    "vid": "vid",
}


def _compare(gt: dict, block: dict) -> list[tuple[str, bool, object, object]]:
    results: list[tuple[str, bool, object, object]] = []
    for gt_key, gt_val in gt.items():
        if gt_key == "address":
            got = block.get("address")
            # Loose check: every comma-separated chunk of the GT address (sans the
            # trailing pincode segment) must appear in the extracted address.
            ok = bool(got)
            if ok:
                for chunk in gt_val.split(","):
                    chunk = chunk.strip()
                    if chunk.startswith("-") or chunk.replace(" ", "").isdigit():
                        continue
                    # strip a trailing " - pincode" tail from the chunk
                    core_chunk = chunk.split(" - ")[0].strip()
                    if core_chunk and core_chunk not in got:
                        ok = False
                        break
            results.append(("address", ok, gt_val, got))
            continue
        block_key = _EXACT_KEYS.get(gt_key, gt_key)
        got = block.get(block_key)
        results.append((gt_key, got == gt_val, gt_val, got))
    return results


def verify() -> int:
    from core.pipeline import scan

    items = render_all()
    all_ok = True
    print("\n=== Verifying clean images through the real pipeline ===")
    for item in items:
        image_path = REPO_ROOT / item.file
        d = scan(str(image_path)).to_dict()
        doc_type = d["documentType"]
        block = d.get("aadhaarFields") or {}
        routed_ok = doc_type == "aadhaar"
        print(f"\n{item.file}")
        print(f"  documentType = {doc_type}  (expected 'aadhaar')  -> {'OK' if routed_ok else 'FAIL'}")
        if not routed_ok:
            all_ok = False
            print(f"  probeText = {json.dumps(d.get('probeText'))}")
        comparisons = _compare(item.fields, block)
        for key, ok, expected, got in comparisons:
            mark = "OK" if ok else "FAIL"
            print(f"    [{mark}] {key}: expected={expected!r} got={got!r}")
            if not ok:
                all_ok = False
    print("\n=== RESULT:", "ALL CLEAN IMAGES PASS" if all_ok else "FAILURES PRESENT", "===")
    return 0 if all_ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Scan rendered images through the real pipeline and check fields")
    args = parser.parse_args()

    if args.verify:
        return verify()

    render_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
