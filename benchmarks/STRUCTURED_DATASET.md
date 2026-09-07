# Structured-document accuracy dataset

**Representative release accuracy: not measured.** A small public smoke suite now
measures US licences, passport-card fronts and W-9s; see the
[repeated multi-document evaluation](MULTIDOC_EVALUATION.md). It does not cover all
eight profiles or meet this document's release-dataset requirements.
Parser regressions and a generated PDF417 encode/decode round trip verify
implementation behavior; they do not establish production OCR accuracy.

`structured_accuracy.py` reuses the KYC evaluator's classification, acceptance,
field, complete-record, and capture/design slice metrics, reading `documentFields`
for every profile. Run it with a private dataset:

```bash
uv run python -m benchmarks.structured_accuracy \
  --manifest /secure/document-eval/manifest.json \
  --dataset-root /secure/document-eval \
  --output /secure/document-eval/reports/release.json
```

Exit codes are 0 for passed measured gates, 1 for measured failures, and 2 for
invalid manifests, missing assets, or setup failures. The checked-in
`structured_manifest.example.json` deliberately has no samples and fails
validation; it cannot generate a passing accuracy claim.

| Profile | Exact identifiers | Initial image/design coverage |
|---|---|---|
| `us_driver_license` | `documentNumber` | issuing jurisdictions, AAMVA versions 8–11, front/back, readable/missing/damaged PDF417, OCR/barcode disagreement |
| `us_state_id` | `documentNumber` | actual ID subfiles, separate state-ID designs, front/back, damaged barcode |
| `passport_card` | `documentNumber` | verified US/other issuer IP TD1 designs, front/back, dates, extended document numbers |
| `us_green_card` | `uscisNumber`, `cardNumber` | verified C1/C2 generations, issuer-specific country-of-birth field, redesign variants |
| `us_ead` | `uscisNumber`, `cardNumber` | verified IA generations, validity dates, category, redesign variants |
| `visa` | `documentNumber` | both MRV-A and MRV-B, issuing countries, all individual check digits |
| `us_i94` | `i94Number`, `passportNumber` when present | numeric/alphanumeric numbers, dated admit-until and `D/S`, native PDF and capture |
| `us_w9` | `taxpayerId` | SSN/EIN, separate legal/business names, blank fields, printed/handwritten captures |

Dates use exact `YYYY-MM-DD`; I-94 `admitUntil` also permits literal `D/S`.
Identifiers must be strings so leading zeroes survive. `uscisNumber` and
`cardNumber` are separate fields. A name match cannot compensate for an ID/date
error: `structuredThresholds` gates exact identifier/date accuracy globally and
for each profile. W-9 has no date metric and reports its denominator as absent.
Normalized scores remain diagnostic and cannot bypass these exact gates.

Use the existing [KYC manifest fields](KYC_DATASET.md) for issuer, design/year,
language/script, side, capture quality, thresholds and required slices. This
wrapper adds the following requirements:

- All eight canonical `requiredDocumentTypes` must have accepted positives and
  unrelated negative controls. A partial dataset cannot pass a suite-wide gate.
- Every sample has an opaque `groupId`, shared by every image/crop/perturbation
  of the same underlying document or holder. Declare top-level `split` as
  `tuning` or `release`; all sample splits must agree. Keep cross-manifest split
  membership in a private catalog—the evaluator cannot inspect other manifests.
- `minimumIndependentGroups` sets positive and unrelated-negative group counts
  **per profile**, separately from image/sample counts. Repeated captures do not
  increase these group counts. Reused asset paths are rejected.
- Accepted `requiredFields` include the registry's full core required set. Every
  required annotation is nonempty. Unknown field names are rejected.
- Optional absent fields may be `null`; they are excluded from field-accuracy
  denominators, rather than awarding successful extraction credit for emptiness.
- Release reports contain counts and match booleans, never extracted/expected
  identity values. Use opaque sample IDs because IDs appear in reports.

Include two kinds of negative input. Corrupt/partial family documents can retain
that family's classification target with `accepted: false`. Unrelated controls
must set `classificationTarget: "unknown"`; only these count toward the required
independent negative coverage. Useful controls include ordinary text mentioning
“driver license” or “W-9”, blank IRS templates, a letter containing an SSN,
non-AAMVA PDF417, conflicting front/back data, and mixed documents. Set acceptance
from a documented legibility/completeness policy before running the scanner.

A negative control uses the same capture metadata as a positive sample:

```json
{
  "id": "opaque-negative-001",
  "groupId": "opaque-source-001",
  "asset": "release/opaque-negative-001.png",
  "documentType": "us_w9",
  "expected": {
    "accepted": false,
    "classificationTarget": "unknown",
    "fields": {},
    "requiredFields": []
  }
}
```

This is a fragment; issuer/design/capture metadata is also mandatory. Independently
annotate twice, adjudicate disagreements, obtain consent/licensing for specimens,
and lock release assets before tuning. Declare required per-document slices and
sample/group minima based on the intended deployment. No minimum in the example
constitutes a statistical accuracy guarantee.
