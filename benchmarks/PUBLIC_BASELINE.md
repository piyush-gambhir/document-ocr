# Public sample OCR baseline

Historical initial baseline. See [measured MRZ improvements](MRZ_IMPROVEMENTS.md)
for the subsequent fixes and comparison.

Measured on 2026-09-07 against OCR commit `17c952e`. The [JSON report](reports/public-data/baseline.json)
records the corpus fingerprint, scorer hash, dependency versions, cached model hashes,
hardware and per-case outcomes. Raw responses remain ignored under `benchmark-data/`.

All 40 original images were submitted to `core.pipeline.scan`, with normal
preprocessing and default language configuration. One warmup preceded measurement.
Five US licences were also submitted with explicit US licence hints. This measures
the local implementation shared by the APIs, not HTTP transport, deployed workers,
cold starts, concurrency, or billing. No OCR logic or input quality gates were changed.

| Measurement | Result |
| --- | ---: |
| All images: success / failure / unsupported | 12 / 24 / 4 |
| Uncaught runtime exceptions | 0 |
| Passport scored fields | 94 / 128 (73.44%) |
| Passport exact MRZ pairs | 10 / 16 (62.5%) |
| Passport images with all eight scored fields correct | 10 / 16 |
| Passport warm median / p95 | 628 / 851 ms |
| US licence fields, auto routing | 0 / 20 |
| US licence fields, explicit hints | 0 / 20 |

The passport subset has only **four independent identities**, each in four
capture modes. These percentages describe the fixed smoke sample, not production
accuracy. A single pass does not establish a stable latency distribution.
Do not interpret fast input rejection as efficient recognition.

## Findings

- **Photo capture is the weakest passport case:** only 7/32 fields and 0/4 full
  MRZ pairs match. Rotated scans match 32/32 fields and 4/4 MRZ pairs. Upright
  scans match 24/32 fields; templates match 31/32. Inspect document localization,
  preprocessing and MRZ detection on the failed photos before choosing a fix.
- **Success is insufficient:** the Latvia template and Serbia photo return
  success but have incorrect `givenNames`. Checksum/identifier validity cannot
  establish name accuracy. These must remain visible as per-field regressions.
- **US coverage is blocked before OCR:** every SD image is 795×487; the current
  minimum shortest side is 600. All five return `RESOLUTION_TOO_LOW`, with or
  without hints. This does not establish US extractor accuracy. Evaluate the
  quality policy separately before deciding whether to change it; do not silently
  upscale fixtures or bypass the gate to improve this baseline.
- **Other families need independent scoring adapters:** the eight generic ID,
  eight LAIT and three receipt images were executed, but receive status/routing
  observations only. LAIT includes blur and identifier failures; receipts are not
  currently a registered extraction profile. No field accuracy is claimed for
  these 19 images. Their failures are not all evidence of an OCR defect.

## Scoring and reproduction

```bash
python -m benchmarks.public_data fetch-samples
python -m benchmarks.public_accuracy --output benchmark-data/public-run/report.json
```

Run serially from the repository root with its installed OCR dependencies and
models. Raw output uses `benchmark-data/public-run/raw.json`; subsequent runs
replace it. The command records observations and does not enforce a release gate
or replace an accepted baseline automatically. Review any committed baseline update.

Passport expectations come directly from the publisher's annotated MRZ lines,
using fixed TD3 positions independently of the production parser. Eight fields
are scored: surname, given names, passport number, issuing country, nationality,
birth date, sex and expiry date. Name filler characters become spaces. Dates are
compared as YYMMDD: century inference is not tested by these labels. MRZ exactness
requires both complete source lines unchanged. All 16 inputs remain in the
accuracy denominator, including rejected inputs. Field credit requires correct
routing but can record a correctly extracted field in a failure response; status
is reported separately. “All scored fields” does not mean every profile field.

US expectations use publisher basic metadata for document number, birth date,
expiry date and issue date; source MM/DD/YYYY is normalized to ISO. Name, address,
barcode and complete-record accuracy are not claimed. Other images do not enter
field denominators. Expected answers are never derived from our OCR output.

Next, build small reviewed samples and field adapters for each supported profile,
including negative/partial cases. Keep these observed failures as fixed cases,
compare base/candidate on identical assets and models, and report improvements
and new regressions separately. No model training or full dataset mirror is needed.
