# TODOs

_Five of the original six items (model-init error handling, Lambda deploy,
TypeScript SDK tests, back-page accuracy, Cloud Run deploy) were completed in
1.2.0 — see CHANGELOG.md._

## Open

1. **Build a licence-clean evaluation dataset.** Source consented, properly
   anonymized documents or unmistakably synthetic specimens for the private
   `benchmark-data/` suite. Do not commit identity documents to this repository.

2. **Populate and lock the KYC image benchmark.** The versioned evaluator,
   manifest schema, variant slices, and release gates now exist, but the
   repository intentionally contains no identity-document images. Build the
   consented private dataset, establish baselines for all six non-passport
   document types, and require the locked split before release.

3. **Regional-script OCR coverage.** KYC-only model selection can now be
   configured with `DOCUMENT_OCR_KYC_LANGS`, but automatic selection and
   Bengali recognition are unavailable. Measure every configured language
   slice and add models only where the locked dataset demonstrates a gain.

4. **Deskew in the preprocessor.** `core/preprocessor.py` does document-boundary
   perspective correction but no text-line deskew, so rotated/tilted inputs shift
   the spatial label→value relationships the extractors rely on. A Hough /
   projection-profile deskew step would harden real-world phone-photo accuracy.

5. **Broader multi-page semantics.** Grouped pages and conflict detection now
   exist. Add typed table/continuation merging and holder association for NPR,
   NREGA and document packets using representative fixtures.

6. **Evaluate routing and US layouts.** Country/document hints and structured
   US routing are implemented. Measure automatic classification confusion and
   each new experimental profile on separate tuning and locked image sets.

7. **Driving licence layout variance.** The DL extractor is best-effort; layouts
   differ substantially by issuing state. Gather fixtures from more states
   (especially Smart Card DLs and the newer Parivahan format) and tune
   `core/driving_licence_extractor.py`. The DL identifier format check in
   `core/validators.py` is also loose — tighten per-state if needed.

8. **Aadhaar name detection.** Aadhaar has no Latin label for the holder name, so
   `_find_name` infers it spatially relative to the DOB line. Validate against
   more real layouts (vertical/horizontal cards, masked Aadhaar, mAadhaar PDF).

9. **Calibrate confidence and latency on the locked dataset.** Passport scans
   now read the full page even after a valid cropped MRZ, exposing visual fields
   and mismatches but adding OCR work. Measure field gains, false rejections,
   and p50/p95 latency before tuning crops, thresholds, or model settings.

## Implemented in 3.1.0

See FEATURES.md and HOSTING.md for contracts, limitations and validation.

- Country-aware profiles, AAMVA PDF417, TD1 passport/US cards, MRV visas,
  I-94 and W-9 extraction; new profiles remain experimental.
- Native PDF text, source evidence, grouped pages and independent batches.
- Review/edit/export UI, selected raster redaction, encrypted persistent-server
  jobs with retention and signed metadata-only callbacks.
- Cloud Run, Lambda/S3, Cloudflare Worker+Container, Compose/Caddy, Terraform,
  and an npm init/doctor/deploy CLI with generated-source dry runs.

Still planned: bank statements/utility bills/payslips, GST/Udyam/incorporation/
cheque schemas, signed Aadhaar QR with current trusted fixtures, and distributed
cloud job backends. None are advertised as implemented document profiles.

## Completed in the September 2026 audit

- Fixed MRZ century/calendar parsing, paired-line detection, and checksum gates.
- Preserved whole identifier boundaries instead of truncating malformed values.
- Added full-page passport recovery/enrichment and rejected empty back pages.
- Unified image decoding for paths/uploads, including HEIF and EXIF orientation;
  preserved 16-bit scan contrast and fixed rotated-quadrilateral corner ties.
- Made benchmark coverage fail closed and preserved Indic marks in scoring.
- Fixed HTTP retry semantics, deadlines, Lambda cleanup, local-server lifecycle,
  and native OCR serialization after HTTP timeouts.
- Removed the duplicate CI workflow and verified redundant code/tests.
- Added `make smoke` for repeatable real-model synthetic regression checks.

## Completed in 3.0.0

- Added NREGA job-card and NPR-letter extraction, classification, public result
  contracts, and deterministic variation tests.
- Added fail-closed non-passport completeness/identifier/semantic assessment.
- Added the private KYC benchmark framework with versioned manifests,
  per-document/per-field metrics, variation slices, and threshold gates.
- Kept dedicated passport modules and passport-positive routing unchanged; new
  KYC families use only the existing unknown/no-text routing boundary.
