# Changelog

## 1.2.0 — 2026-06-07

### Multi-document support (additive, backward-compatible)
- New document-type router (`core/document_classifier.py`) detects passport,
  PAN, Aadhaar, driving licence, and voter ID from full-page OCR using keyword
  hints + identifier-format signals, then dispatches to a per-document extractor.
- New extractors: `pan_extractor`, `aadhaar_extractor` (front + back),
  `driving_licence_extractor`, `voter_id_extractor` — same TextRegion-in /
  dataclass-out shape as the existing passport extractors, reusing the
  `core/validator.py` spatial helpers. Each handles real-world layout variation
  (label above vs beside value, bilingual Hindi/English labels, OCR noise):
  - **PAN**: holder-type-aware PAN detection (never sliced from a date/DL no.),
    name-vs-father disambiguation across NSDL + e-PAN layouts.
  - **Aadhaar**: VID (16-digit) isolated from the 12-digit number, masked-Aadhaar
    handling (`aadhaarMasked` / `aadhaarLast4`), Hindi gender, name-above-DOB
    heuristic, back-page address/pincode. Adds `vid`, `aadhaarMasked`, `aadhaarLast4`.
  - **Driving licence**: dates disambiguated strictly by adjacent label (DOB vs
    issue vs validity), NT/TR dual validity (`validityDateTransport`), plus
    `relationName`, `bloodGroup`, `classOfVehicle`.
  - **Voter ID**: name-vs-relation disambiguation, relation typing
    (`relationType` = father/husband/mother), Hindi gender, DOB-or-age fallback.
- New identifier validators (`core/validators.py`): PAN format + holder-type
  char, EPIC format, DL format, and the **Verhoeff** checksum for Aadhaar.
- `core/validator.py` gains reusable `find_visual_value_right` and
  `find_label_value` helpers (cards lay values beside labels, not just below).
- **Output contract is purely additive.** Passport responses are unchanged;
  results now also carry `panFields` / `aadhaarFields` / `drivingLicenceFields` /
  `voterIdFields` (null unless that `documentType` matched). TS types extended
  accordingly. No existing key removed, renamed, or reshaped.

### TODO backlog cleared
- **Model-init error handling**: `core/ocr_engine.py` raises `OCRModelInitError`
  (`MODEL_INIT_FAILED`) instead of hanging when models can't load; the server
  reports it via `/ready` (503) and `/scan` (503), and a failed init is never
  cached so a later request can retry.
- **AWS Lambda**: `deploy/lambda/` (handler + `Dockerfile.lambda` + SAM
  `template.yaml`), matching the SDK's `mode: 'lambda'` payload.
- **Cloud Run**: `deploy/cloudrun/` (`service.yaml` + `deploy.sh` + `cloudbuild.yaml`).
- **Back-page accuracy**: state names are now normalised to canonical title case
  on every address-parsing path (not just the comma-tokenized one).
- **TypeScript SDK tests**: scan/retry-on-5xx/422-body/400-throw/timeout against a
  real ephemeral server, plus full `normalizeToBlob` / `normalizeToBase64` coverage.

### Tests
- 90 → 234 passing Python tests (each KYC extractor has deterministic
  TextRegion-fixture coverage across many layouts/edge cases); 12 → 24 TypeScript
  tests. Passport benchmark still green on `sample-passports/`.

## 1.1.0 — 2026-04-25

### Detection robustness
- `_detect_document` now sanity-checks the 4-corner approximation (≥30% image
  area, convex, aspect 0.5–3.0). Previously a noise contour from page perforations
  could be returned as the document boundary and silently warp the page into
  a useless strip during perspective correction. Affected images that fill
  the frame (flat scans without surrounding background).
- `preprocess` validates the perspective-corrected output area; if the warp
  collapses the image to <50% of input it is discarded and the raw image is
  used instead. Defense in depth.
- Pipeline failure path no longer hardcodes `pageType: "passport_biodata"`
  when zero text is detected — returns `pageType: "unknown"` instead.

### Back-page extraction accuracy
- New `find_label_row_left_edge` helper: value lookup uses the leftmost edge
  of the bilingual label *block* (Hindi + English / Arabic + English /
  Cyrillic + English etc.), not just the English region. Conservative
  absorption (≤5 alphanumeric chars) prevents accidental capture of values
  from adjacent fields in multi-column layouts.
- `_collect_multiline_value` is now row-aware — stop labels in adjacent
  columns are recognised, and Hindi-script noise rows are filtered out of
  collected addresses.
- New `_extract_old_passport_row`: Indian passport renewal information sits
  under a single compound label (`Old Passport No. with Date and Place of
  Issue`) covering three columnar values. The new extractor classifies them
  by content shape (passport-number regex, date regex, remaining text). Uses
  `re.fullmatch` so a long file number like `DL2072369058018` cannot have
  `L2072369` sliced out of it as a passport number.
- `_parse_address` adds a comma-tokenized scan that recognises state names
  (and 2-letter codes) anywhere in the address — populates `city` and `state`
  for formats like `"NEW MAHAVIR NAGAR,DELHI,INDIA"`. State output is
  normalised to canonical title case.

### Tests
- 80 → 90 passing Python tests. New: quad plausibility, document-detection
  edge cases, preprocess fallback when no boundary is found, bilingual-label
  prefix handling, multi-column adjacent-value resistance, full Indian
  back-page integration test, 3-column old-passport row, file-number / passport-
  number disambiguation, comma-tokenized address parsing.
- TypeScript suite (12 tests) passes — no SDK shape changes.

### Output contract — same field names, more fields populated
On Indian passport back pages, these previously-`null` fields now populate
when the source data is present:
- `backPageFields.city`
- `backPageFields.state` (canonical title case, e.g. `"Delhi"`)
- `backPageFields.oldPassportDateOfIssue`
- `backPageFields.oldPassportPlaceOfIssue`

No fields removed, renamed, or changed shape. Consumers do not need to
adjust types.

## 1.0.0
- Initial release with RapidOCR-based pipeline, biodata + back-page support.
