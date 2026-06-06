#!/usr/bin/env python3
"""
Generate a clean, synthetic specimen passport biodata image for benchmarking.

The watermarked sample images (`SAMPLE - IMMIHELP.COM`) corrupt some OCR output,
making the accuracy benchmark unreliable (see TODOS.md #3). This renders a fully
synthetic TD3 passport biodata page with:

  * a machine-readable zone (MRZ) whose ICAO check digits are computed to be
    valid (via core.mrz_parser.icao_check_digit), and
  * visual fields matching the MRZ.

The expected output is printed as a manifest.json fragment so the image can be
wired into benchmarks/accuracy.py — but ONLY if it reads back cleanly through
the real pipeline. Run with `--verify` to scan the rendered image and check.

Usage:
    uv run python scripts/generate_synthetic_passport.py [--verify] \
        [--out sample-passports/synthetic-specimen-passport.png]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mrz_parser import icao_check_digit  # noqa: E402

# ---------------------------------------------------------------------------
# Specimen identity (all fictitious)
# ---------------------------------------------------------------------------

SURNAME = "SPECIMEN"
GIVEN_NAMES = "JOHN ROBERT"
PASSPORT_NUMBER = "L8988901"
NATIONALITY = "IND"
COUNTRY = "IND"
DOB_YYMMDD = "900115"          # 1990-01-15
DOB_ISO = "1990-01-15"
SEX = "M"
EXPIRY_YYMMDD = "290115"       # 2029-01-15
EXPIRY_ISO = "2029-01-15"
DOB_DISPLAY = "15/01/1990"
EXPIRY_DISPLAY = "15/01/2029"
ISSUE_DISPLAY = "16/01/2019"
PLACE_OF_BIRTH = "NEW DELHI"

MONO_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
SANS_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _pad_field(value: str, width: int) -> str:
    return value.ljust(width, "<")[:width]


def build_mrz() -> tuple[str, str]:
    """Build the two 44-char TD3 MRZ lines with valid ICAO check digits."""
    name_field = _pad_field(f"{SURNAME}<<{GIVEN_NAMES.replace(' ', '<')}", 39)
    line1 = f"P<{COUNTRY}{name_field}"
    assert len(line1) == 44, (len(line1), line1)

    pn_field = _pad_field(PASSPORT_NUMBER, 9)
    pn_check = str(icao_check_digit(pn_field))
    dob_check = str(icao_check_digit(DOB_YYMMDD))
    expiry_check = str(icao_check_digit(EXPIRY_YYMMDD))
    personal_field = "<" * 14
    personal_check = str(icao_check_digit(personal_field))

    head = f"{pn_field}{pn_check}{NATIONALITY}{DOB_YYMMDD}{dob_check}{SEX}{EXPIRY_YYMMDD}{expiry_check}"
    composite_tail = f"{personal_field}{personal_check}"
    body = head + composite_tail  # 43 chars

    # Overall check digit is computed over the exact composite the parser uses:
    # line2[0:10] + line2[13:20] + line2[21:43].
    line2_no_overall = body
    composite = line2_no_overall[0:10] + line2_no_overall[13:20] + line2_no_overall[21:43]
    overall_check = str(icao_check_digit(composite))
    line2 = line2_no_overall + overall_check
    assert len(line2) == 44, (len(line2), line2)
    return line1, line2


def render(out_path: Path) -> tuple[str, str]:
    line1, line2 = build_mrz()

    width, height = 1100, 700
    margin = 40
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    label_font = _load_font(SANS_FONT_CANDIDATES, 20)
    value_font = _load_font(SANS_FONT_CANDIDATES, 26)
    title_font = _load_font(SANS_FONT_CANDIDATES, 30)

    # Auto-fit the MRZ font so all 44 monospace chars fit within the margins.
    # If the line overflows the canvas the right-most characters (the trailing
    # check digits) get clipped, which silently breaks checksum validation.
    mrz_max_width = width - 2 * margin
    mrz_size = 38
    mrz_font = _load_font(MONO_FONT_CANDIDATES, mrz_size)
    while mrz_size > 18 and draw.textlength(line2, font=mrz_font) > mrz_max_width:
        mrz_size -= 1
        mrz_font = _load_font(MONO_FONT_CANDIDATES, mrz_size)

    draw.text((40, 24), "REPUBLIC OF INDIA  /  PASSPORT", font=title_font, fill="black")
    draw.line((40, 70, width - 40, 70), fill="black", width=2)

    # Two-column biodata block: (label, value, x, y)
    rows = [
        ("Type", "P", 40, 100),
        ("Country Code", COUNTRY, 300, 100),
        ("Passport No.", PASSPORT_NUMBER, 560, 100),
        ("Surname", SURNAME, 40, 175),
        ("Given Names", GIVEN_NAMES, 40, 250),
        ("Nationality", "INDIAN", 40, 325),
        ("Sex", "M", 300, 325),
        ("Date of Birth", DOB_DISPLAY, 560, 325),
        ("Place of Birth", PLACE_OF_BIRTH, 40, 400),
        ("Date of Issue", ISSUE_DISPLAY, 40, 475),
        ("Date of Expiry", EXPIRY_DISPLAY, 560, 475),
    ]
    for label, value, x, y in rows:
        draw.text((x, y), label, font=label_font, fill=(90, 90, 90))
        draw.text((x, y + 26), value, font=value_font, fill="black")

    # MRZ band at the bottom, monospace, high contrast.
    draw.rectangle((0, height - 130, width, height), fill="white")
    draw.line((margin, height - 130, width - margin, height - 130), fill="black", width=1)
    draw.text((margin, height - 110), line1, font=mrz_font, fill="black")
    draw.text((margin, height - 60), line2, font=mrz_font, fill="black")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return line1, line2


def expected_manifest_entry(out_path: Path, line1: str, line2: str) -> dict:
    return {
        out_path.name: {
            "status": "success",
            "documentType": "passport",
            "pageType": "passport_biodata",
            "fields": {
                "surname": SURNAME,
                "givenNames": GIVEN_NAMES,
                "fullName": f"{GIVEN_NAMES} {SURNAME}",
                "passportNumber": PASSPORT_NUMBER,
                "nationality": NATIONALITY,
                "dateOfBirth": DOB_ISO,
                "sex": SEX,
                "expiryDate": EXPIRY_ISO,
                "countryCode": COUNTRY,
            },
            "mrzRaw": [line1, line2],
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "sample-passports"
        / "synthetic-specimen-passport.png",
    )
    parser.add_argument("--verify", action="store_true", help="Scan the rendered image and report readback")
    args = parser.parse_args()

    line1, line2 = render(args.out)
    print(f"Rendered specimen passport → {args.out}")
    print(f"MRZ line 1: {line1}")
    print(f"MRZ line 2: {line2}")
    print("\nManifest fragment:")
    print(json.dumps(expected_manifest_entry(args.out, line1, line2), indent=2))

    if args.verify:
        from core.pipeline import scan

        print("\nScanning rendered image through the real pipeline...")
        result = scan(str(args.out))
        d = result.to_dict()
        print(f"  status={d['status']} pageType={d['pageType']} mrzValid={d['mrzValid']}")
        print(f"  fields={json.dumps(d.get('fields'))}")
        clean = (
            d["status"] == "success"
            and d["pageType"] == "passport_biodata"
            and d["mrzValid"]
            and (d.get("fields") or {}).get("passportNumber") == PASSPORT_NUMBER
        )
        print(f"\nReadback clean enough for benchmark: {clean}")
        return 0 if clean else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
