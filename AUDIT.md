# Document OCR audit — 7 September 2026

The review found reproducible extraction errors and misleading validation gaps,
not a need to replace the OCR engine. The working tree now contains fixes for
passport extraction, image decoding, identifier validation, benchmark scoring,
server execution, and the Node.js SDK.

The subsequent implementation adds the features described in [FEATURES.md](FEATURES.md)
and the deployment kits in [HOSTING.md](HOSTING.md). The initial audit measurements
below are preserved as a baseline; see the final verification section for the
expanded suite. Hints, grouped pages and US structured routing supersede the
corresponding original follow-up items.

## Verified extraction improvements

A real RapidOCR run on two generated text-only specimens reproduced three errors
in the original checkout. The same specimens pass after the changes:

| Synthetic passport field | Original result | Updated result |
|---|---|---|
| Expiry date | `1935-08-15` | `2035-08-15` |
| Place of birth | Missing | `NEW DELHI` |
| Date of issue | Missing | `15/08/2025` |

The PAN specimen continues to return its expected identifier, name, and DOB.
Across the two specimens, the original checkout matched 7 of 10 annotated checks;
the updated checkout matches all 10. These checks include routing and MRZ validity,
so this is a regression result, not a field-accuracy estimate. Both specimens are
clearly marked synthetic and use no issuer artwork. No real identity documents
were used, downloaded, or added to the repository.

Reproduce with `make smoke` or
`.venv/bin/python scripts/ocr_smoke.py --cases pan passport --output /tmp/ocr-smoke.json`.
The default smoke run now additionally covers a synthetic US W-9.
An optional `--code-root /path/to/checkout` compares another source checkout with
the same interpreter, models, and specimens. The script exits nonzero on a
regression and removes its temporary images.

Full-page passport OCR supplies missing visual fields and checks even when the
initial crop has a valid MRZ. This costs an additional recognition pass. Updated
synthetic passport runs varied from about 0.9 to 5.3 seconds on this machine;
the few original runs took about 1.1–1.2 seconds. These variable, single-sample
runs do not establish a reliable latency comparison. Measure warm p50/p95 on
representative documents before changing the crop strategy or release target.

## Changes

- MRZ parsing resolves centuries by field/date context, validates calendar dates,
  anchors paired lines to a TD3 header, and verifies optional-data checksums.
  Passport classification recognizes MRZ lines with fully populated optional
  data. Impossible dates prevent a successful extraction even when their check
  digits pass. Valid unknown date components remain explicitly incomplete.
- Full-page OCR can recover a passport missed by the bottom crop. Passport back
  pages with no extracted values now fail rather than returning empty success.
  A checksum-valid cropped reading survives a weaker full-page reading.
- PAN, EPIC, and driving licence normalization preserves token boundaries,
  preventing overlong identifiers from being truncated into valid strings.
  Non-ASCII checksum inputs no longer crash Verhoeff validation.
- File paths and uploaded bytes share image decoding, including EXIF rotation
  and mirroring, HEIC/HEIF uploads, and preserved 16-bit grayscale contrast.
  Rotated document quadrilaterals retain four distinct corners. Invalid images
  and PDFs produce structured input failures.
- Passport benchmark gates require actual coverage and score back-page fields
  and annotated metadata. KYC scoring retains meaningful Indic combining marks,
  avoids duplicate slice counts, and compares thresholds before rounding.
  Runtime errors and misclassified records cannot earn misleading accuracy credit.
- SDK retries use HTTP status codes; permanent 4xx errors stop immediately.
  Timeouts cover image downloads, Lambda clients are disposed, and local-server
  startup/shutdown clean up polling, listeners, and timers. npm lockfile download
  URLs use the official registry without version or integrity changes.
- HTTP OCR timeouts retain the worker's concurrency slot until native execution
  ends. Client cancellation likewise cannot start overlapping OCR work. Upload
  reads are bounded to the documented limit plus one byte.

## Cleanup and test quality

Removed the duplicate `.github/workflows/test.yml`; `.github/workflows/ci.yml`
already runs Python tests, SDK tests/typecheck, builds, and package checks on PRs.
Also removed a no-op pytest configuration file, duplicate serializers, an unused
fallback parameter/helper, unreachable classifier code, unused imports, and a
redundant normalization test. Replaced random-noise blur testing with a sharp
text specimen and added the missing glare assertion.

The original ICAO MRZ specimen was valid. Its old OCR-correction test changed the
DOB to the wrong value and asserted that value without requiring valid check
digits. It was replaced with faithful corruption and checksum regressions.
SDK tests now exercise public lifecycle and transport behavior instead of trivial
constructors and private-method readiness checks. Useful existing extractor
layout tests remain: feeding OCR regions directly is appropriate for testing
spatial parsing, but does not measure image recognition.

Independent review checked the pipeline/decoder and server cancellation paths.
It caught a 16-bit decoder regression during implementation, which is fixed and
covered by PNG/TIFF known-level tests. Additional regressions cover fresh-process
HEIF decoding, independent EXIF transforms, all corner permutations, competing
MRZ readings, and semaphore retention after timeout.

## Verification

- Original Python suite: **332 passed, 2 skipped**.
- Updated Python suite: **448 passed, 2 skipped**.
- Updated TypeScript suite: **55 passed**, including real localhost HTTP tests.
- Python source distribution and wheel builds pass.
- SDK typecheck, ESM/CommonJS builds, declarations, runtime imports, and package
  dry run pass.
- Real-model synthetic PAN and passport smoke checks pass.
- `git diff --check` passes.

The two skipped Python tests require the private image dataset. No such dataset
is configured or present. Lambda transport and Python child-process lifecycle
are mocked in SDK tests; no live AWS invocation, deployment, or publishing was
performed. The smoke test does not cover regional scripts or other KYC families.

## Next accuracy work, in priority order

1. **Establish the image baseline.** Populate consented/private tuning and locked
   test splits following `benchmarks/PASSPORT_DATASET.md` and
   `benchmarks/KYC_DATASET.md`. Include negative controls and holder-disjoint
   layout, language, capture, and quality slices. The gates now make missing
   evaluation evidence visible rather than reporting perfect scores.
2. **Resolve ambiguous routing explicitly.** Positive passport probes still
   take precedence. Some driving licences and voter cards with passport-like
   labels can remain on that path. A caller-supplied document hint or explicit
   KYC entry point should have a shared Python/HTTP/SDK contract and dedicated
   ambiguity fixtures before automatic routing is changed.
3. **Measure orientation and script gaps.** EXIF orientation is handled; photos
   rotated without metadata and text-line skew still need a measured orientation/
   deskew strategy. Configured regional recognizers need per-script evaluation;
   the English-to-Latin fallback is not a general Indic-script detector.
4. **Define multi-page extraction.** PDFs still use the first page. NPR letters,
   NREGA continuations, and front/back cards need page association and conflict
   handling before aggregation can be claimed.
5. **Calibrate fields and confidence.** Prioritize Aadhaar name placement,
   state-specific driving licence layouts, field-specific confidence, glare
   heuristics on white paper, and passport cross-field mismatch thresholds.
   Keep unknown fields explicit; tune only against an independent test split.

Two-digit MRZ birth years cannot by themselves distinguish people a century
apart. Visual dates are needed to resolve that ambiguity. Identifier checks
remain offline format/checksum checks, not document-authenticity verification.

## Implementation references

The decoder follows Pillow's [EXIF transpose behavior](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose)
and the [pillow-heif opener API](https://pillow-heif.readthedocs.io/en/latest/reference/API.html).
The optional MRZ data check follows [ICAO Doc 9303, Part 4](https://www.icao.int/publications/documents/9303_p4_cons_en.pdf).

## 3.1 implementation verification and independent review

The expanded suite exercises PDF417 image decoding, MRZ/US structured parsing,
native-text PDFs, grouping conflicts, exact PDF CropBox evidence alignment,
raster redaction, HTTP options/batches/jobs, S3 restrictions, encrypted queue
restart/leases/deletion, and signed metadata-only notifications. Browser checks
used a generated W-9 and confirmed extraction, a correction, and a redacted PNG.
No real identity records were uploaded or used.

Independent review caught and fixed queue waits outside the request deadline,
wrong encryption keys destroying pending work, CropBox coordinate mismatch in
redaction, synchronous SQLite work blocking the event loop, and late UI responses
restoring data after Clear. The regression tests reproduce these failure modes.

Hosting checks cover Cloudflare tests/type generation/typecheck/Worker dry run,
SAM validation, both Terraform roots, Compose, shell syntax, fail-closed Cloud Run
IAM behavior, and actual Docker/Cloud Build context allowlists. Full native Docker
image builds remain unverified locally: the Docker daemon ran out of disk space;
Cloudflare's full container build also requires the missing Buildx plugin. No
user images were pruned and no cloud resources were deployed.

Final verification: **571 Python tests passed, 2 skipped**; **82 SDK tests**,
**12 Cloudflare gateway tests**, and the **UI Clear regression** passed. Python
wheel/source builds, SDK typecheck/build, installed-package contract checks and
all four CLI scaffold/deploy dry runs passed. The final npm package includes the
same core/server/UI sources used by these tests.
The private image suites remain unavailable, so no nationwide/state-wide US OCR
accuracy or production-ready deployment claim is made.
