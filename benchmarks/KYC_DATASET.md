# Private KYC accuracy dataset

`kyc_accuracy.py` measures the non-passport pipeline against a private,
versioned dataset. Keep identity documents and ground-truth values outside this
repository. Only synthetic, unmistakably non-real smoke fixtures may be used in
public CI.

The evaluator covers these result blocks:

| Document type | Result block |
|---|---|
| `pan` | `panFields` |
| `aadhaar` | `aadhaarFields` |
| `driving_licence` | `drivingLicenceFields` |
| `voter_id` | `voterIdFields` |
| `nrega_job_card` | `nregaJobCardFields` |
| `npr_letter` | `nprLetterFields` |

NREGA and NPR support is experimental until it is measured against a
representative private image set. Do not mark a sample rejected merely because
its design is difficult: `expected.accepted` records whether the input meets
the dataset's declared capture/legibility policy, not whether today's
implementation happens to support it.

## Storage and annotation

- Store assets and manifests in access-controlled, encrypted storage.
- Obtain consent or a clear licence for every non-synthetic specimen.
- Use opaque sample IDs. Do not put names or identifiers in filenames.
- Annotate independently twice and adjudicate disagreements.
- Keep an immutable, locked release-test split separate from tuning data.
- Split by document/holder, not by image. All crops and perturbations derived
  from one source must remain in the same split.
- Record absent fields explicitly as `null`. `requiredFields` defines which
  fields must be correct for complete-record accuracy.
- Nested values such as NREGA `members` may be represented as JSON arrays and
  objects. Their exact and normalized comparisons cover the complete structure.
- For an unrelated negative control, assign it to the document-family bucket
  whose false-positive behavior it tests, set `expected.accepted: false`, and
  set `expected.classificationTarget: "unknown"`. Partial/invalid examples that
  should still be recognized as their family can omit `classificationTarget`.
- Never copy raw expected or actual values into tickets or benchmark reports.
  The generated report contains only counts and match booleans.
- Declare `requiredDocumentSlices` for every document type. This makes missing
  year/design/language/capture values a manifest error rather than
  allowing another document family to satisfy global coverage.

The manifest conforms to `kyc_manifest.schema.json`. The evaluator also performs
the important structural checks itself, so `jsonschema` is not required.

## Variant matrix

Treat design family and issue year as different dimensions. An old design may
remain in circulation years after a redesign, so issue year alone is not a safe
template selector. Verify release ranges from authoritative sources before
adding them to the design catalog.

Start with this matrix and expand it when a new verified design appears:

| Document | Initial design families to collect | Additional mandatory slices |
|---|---|---|
| PAN | legacy physical/value-below, current physical, e-document PDF, enhanced-QR design | issuer, issue-year band, individual/non-individual holder, scan/photo/PDF |
| Aadhaar | letter/e-document, masked e-document, cropped card, PVC front/back, mobile export | front/back/both, DOB/YOB, masked/unmasked, Hindi and regional scripts |
| Driving licence | legacy booklet/laminated, state smart card, standardized transport-platform card | issuing state/RTO, NT/TR classes, front/back, bilingual/regional scripts |
| Voter ID | legacy laminated, color PVC, electronic PDF | state, DOB/age layouts, relation type, bilingual/regional scripts |
| NREGA job card | state-specific legacy and current job-card families | state, household-member table shape, handwritten/printed, page number |
| NPR letter | each verified campaign/issuer layout | issuer/state, year band, language/script, single/multi-page |

For every design family, cover:

- `yearBand`: a verified range such as `2018-2021`, not an inferred date.
- `issuer.name` and `issuer.state`; use `national` or `not_applicable` where
  appropriate.
- BCP-47-style language tags and Unicode script names.
- side/page form: front, back, both, single page, or multi-page.
- capture type: flatbed scan, phone photo, screenshot, native PDF, photocopy.
- quality: resolution, blur, glare, rotation/skew, crop, perspective, and
  compression.

Use `requiredSlices` to make important catalog entries fail closed when no
sample represents them.

## Manifest excerpt

This is one sample excerpt. A valid manifest must include at least one sample
for all six `requiredDocumentTypes`.

```json
{
  "schemaVersion": 1,
  "datasetVersion": "2026-07-27.1",
  "requiredDocumentTypes": [
    "pan",
    "aadhaar",
    "driving_licence",
    "voter_id",
    "nrega_job_card",
    "npr_letter"
  ],
  "requiredSlices": {
    "captureType": ["phone_photo", "native_pdf"],
    "quality.rotation": ["upright", "minor_skew"]
  },
  "requiredDocumentSlices": {
    "pan": {
      "designFamily": ["legacy_physical_value_below"],
      "script": ["Latin"]
    },
    "aadhaar": {
      "designFamily": ["pvc_front"],
      "script": ["Latin", "Devanagari"]
    },
    "driving_licence": {
      "designFamily": ["standardized_transport_platform"],
      "script": ["Latin"]
    },
    "voter_id": {
      "designFamily": ["color_pvc"],
      "script": ["Latin"]
    },
    "nrega_job_card": {
      "designFamily": ["state_current_job_card"],
      "script": ["Latin", "Devanagari"]
    },
    "npr_letter": {
      "designFamily": ["verified_campaign_layout"],
      "script": ["Latin", "Devanagari"]
    }
  },
  "thresholds": {
    "overall": {
      "minClassificationAccuracy": 0.98,
      "minExpectedAcceptanceRate": 0.95,
      "minExactFieldAccuracy": 0.95,
      "minNormalizedFieldAccuracy": 0.97,
      "minCompleteRecordAccuracy": 0.90,
      "minNormalizedCompleteRecordAccuracy": 0.93,
      "maxFalseSuccessRate": 0.01,
      "maxRuntimeErrorRate": 0.0
    },
    "perDocument": {
      "*": {
        "minNormalizedFieldAccuracy": 0.95,
        "maxFalseSuccessRate": 0.02
      },
      "aadhaar": {
        "minNormalizedFieldAccuracy": 0.99
      }
    },
    "perSlice": {
      "dimensions": [
        "designFamily",
        "yearBand",
        "state",
        "captureType",
        "quality.rotation"
      ],
      "minimumSamples": 20,
      "rules": {
        "minNormalizedFieldAccuracy": 0.90,
        "minNormalizedCompleteRecordAccuracy": 0.85
      }
    }
  },
  "samples": [
    {
      "id": "pan-legacy-0001",
      "asset": "locked-test/pan/pan-legacy-0001.png",
      "documentType": "pan",
      "designFamily": "legacy_physical_value_below",
      "yearBand": "verified-pre-2018",
      "issuer": {
        "name": "verified-issuer-code",
        "state": "national"
      },
      "languages": ["en", "hi"],
      "scripts": ["Latin", "Devanagari"],
      "side": "front",
      "capture": {
        "type": "phone_photo",
        "quality": {
          "resolution": "high",
          "blur": "none",
          "glare": "mild",
          "rotation": "minor_skew",
          "crop": "full",
          "perspective": "mild",
          "compression": "mild"
        }
      },
      "expected": {
        "accepted": true,
        "fields": {
          "panNumber": "SYNTHETIC VALUE",
          "name": "SYNTHETIC NAME",
          "fatherName": "SYNTHETIC NAME",
          "dateOfBirth": "01/01/1990"
        },
        "requiredFields": [
          "panNumber",
          "name",
          "dateOfBirth"
        ]
      }
    }
  ]
}
```

## Metrics

The JSON report contains overall, per-document, per-field, slice, and
document-plus-slice results:

- classification accuracy;
- actual acceptance and expected-sample acceptance;
- false rejections and false successes;
- scanner/runtime error rate;
- exact and Unicode-normalized field accuracy;
- exact and normalized complete-record accuracy;
- field presence and match counts.

Release gates use unrounded ratios. Missing denominators fail their gates,
scanner crashes cannot count as correct unknown classifications, and
misclassified documents receive no field-match credit, including for annotated
absent fields. Language and script tags must be unique within a sample so a
single document cannot inflate slice sample counts.

`requiredDocumentSlices` first guarantees that each declared per-document
variant exists in the accepted-positive dataset. Configured `perSlice`
minimum-sample and accuracy gates are then applied both to the global slice and
to every observed document-plus-slice combination. This keeps a strong modern
layout in one document family from hiding a weak legacy/year variant in another.

Required dimensions are checked independently; they do not imply the Cartesian
product of every design, year, language, and capture value. When a specific
combination is release-critical, represent it as its own verified
`designFamily` (or add an explicit sample catalog entry) and require that value.

Exact accuracy is deliberately strict. Normalized accuracy applies Unicode NFKC,
case folding, and removal of whitespace/punctuation while preserving letters,
digits, and combining marks from every script. Vowel signs and other script marks
remain significant; different names must not become equal by dropping them. Report both; do not replace exact identifier accuracy
with a fuzzy score.

Measure accuracy on all submitted samples and conditional acceptance separately.
Otherwise a system can appear accurate simply by rejecting difficult variants.
Include invalid, partial, unrelated, and low-quality samples with
`expected.accepted: false` so false-success rates have a real denominator.
Use `classificationTarget: "unknown"` for unrelated controls so a correct
rejection does not reduce classification accuracy.

Choose release thresholds from product risk, not from the current implementation.
For orientation, estimating performance near 99% to approximately ±1 percentage
point at 95% confidence needs roughly 380 independent examples in an important
slice. Observing zero false successes in roughly 3,000 representative negatives
places the usual rule-of-three upper bound near 0.1%.

## Running

```bash
uv run python benchmarks/kyc_accuracy.py \
  --manifest /secure/kyc-eval/manifest.json \
  --dataset-root /secure/kyc-eval \
  --output /secure/kyc-eval/reports/main.json
```

An optional `--thresholds /secure/thresholds.json` file replaces the manifest
threshold configuration for release-specific gates. The command exits `0` when
all gates pass, `1` for measured threshold failures, and `2` for invalid
manifests or benchmark setup errors.

Run a small PII-free synthetic smoke suite on pull requests. Run the private
locked dataset on a controlled release runner, retain aggregate reports, and
compare every change against the last released baseline.
