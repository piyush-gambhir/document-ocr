"""Run real OCR on synthetic documents. This is not an accuracy benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


# Intentionally artificial text-only specimens with no issuer artwork.
CASES = {
    "pan": {
        "rows": [
            (50, "SYNTHETIC TEST - NOT A VALID DOCUMENT"),
            (160, "INCOME TAX DEPARTMENT"),
            (240, "Permanent Account Number"),
            (310, "ABCPE1234F"),
            (420, "Name"),
            (480, "EXAMPLE PERSON"),
            (590, "Father's Name"),
            (650, "TEST PERSON"),
            (760, "Date of Birth"),
            (820, "15/08/1985"),
        ],
        "expected": {
            "documentType": "pan",
            "panFields.panNumber": "ABCPE1234F",
            "panFields.name": "EXAMPLE PERSON",
            "panFields.dateOfBirth": "15/08/1985",
        },
    },
    "passport": {
        "rows": [
            (45, "SYNTHETIC TEST - NOT A VALID DOCUMENT"),
            (120, "PASSPORT"),
            (180, "Place of Birth"),
            (235, "NEW DELHI"),
            (310, "Date of Issue"),
            (365, "15/08/2025"),
            (430, "Surname"),
            (480, "EXAMPLE"),
            (560, "Given Name"),
            (610, "TEST PERSON"),
            (780, "P<INDEXAMPLE<<TEST<PERSON<<<<<<<<<<<<<<<<<<<"),
            (850, "X1234567<7IND8508155M3508150<<<<<<<<<<<<<<08"),
        ],
        "expected": {
            "documentType": "passport",
            "fields.passportNumber": "X1234567",
            "fields.expiryDate": "2035-08-15",
            "fields.placeOfBirth": "NEW DELHI",
            "fields.issueDate": "15/08/2025",
            "mrzValid": True,
        },
    },
    "us_w9": {
        "rows": [
            (45, "SYNTHETIC TEST - NOT A VALID DOCUMENT"),
            (125, "Form W-9"),
            (200, "Request for Taxpayer Identification Number and Certification"),
            (290, "Name: JANE SAMPLE"),
            (390, "Employer identification number: 12-3456789"),
        ],
        "expected": {
            "documentType": "us_w9",
            "documentFields.name": "JANE SAMPLE",
            "documentFields.taxpayerId": "123456789",
            "documentFields.taxpayerIdType": "ein",
        },
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--code-root", type=Path, default=Path(__file__).resolve().parents[1],
        help="Source checkout to test; defaults to this repository",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--cases", nargs="+", choices=list(CASES), help="Selected smoke cases; default all")
    args = parser.parse_args()
    sys.path.insert(0, str(args.code_root.resolve()))
    from core.pipeline import scan

    report = {}
    with tempfile.TemporaryDirectory(prefix="document-ocr-smoke-") as directory:
        for name, case in CASES.items():
            if args.cases and name not in args.cases:
                continue
            image = np.full((1000, 1800, 3), 240, np.uint8)
            for y, text in case["rows"]:
                cv2.putText(
                    image, text, (75, y + 25), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1, (20, 20, 20), 2, cv2.LINE_AA,
                )
            path = Path(directory) / f"{name}.png"
            if not cv2.imwrite(str(path), image):
                raise RuntimeError(f"Could not write synthetic {name} fixture")
            result = scan(path).to_dict()
            checks = {}
            for key, expected in case["expected"].items():
                actual = result
                for part in key.split("."):
                    actual = actual.get(part) if isinstance(actual, dict) else None
                checks[key] = actual == expected
            report[name] = {
                "status": result["status"],
                "checks": checks,
                "processingMs": result["processingMs"],
                "passed": result["status"] == "success" and all(checks.values()),
            }

    output = {
        "syntheticOnly": True,
        "cases": report,
        "passed": all(case["passed"] for case in report.values()),
    }
    rendered = json.dumps(output, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
