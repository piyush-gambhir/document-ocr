# document-ocr

Local-first OCR pipeline for passports, Indian KYC documents, and experimental US identity/immigration/tax documents. It
preprocesses scans, classifies the document, runs targeted OCR with RapidOCR
(PP-OCRv5), and extracts structured fields—including passport MRZ data, Indian
passport back-page fields, and identifier/holder fields for PAN, Aadhaar,
driving licences, voter IDs, MGNREGA/NREGA job cards, and National Population
Register (NPR) name-and-address letters.

Ships as a Python package with a FastAPI server, plus an npm wrapper at [`packages/passport-ocr`](packages/passport-ocr) that auto-spawns the Python server for Node.js consumers.

> [!IMPORTANT]
> This project is beta software for data extraction. It does not establish
> document authenticity, verify identity against an issuing authority, detect
> fraud, or by itself satisfy KYC obligations. Evaluate it on your own legally
> obtained dataset before production use.

Version 3.1 adds US document profiles, PDF417/TD1/visa parsing, country hints,
field evidence, native PDF text, grouped pages, batch scans, a browser review UI,
redaction, and optional encrypted jobs. See [FEATURES.md](FEATURES.md) for the
contracts and coverage limits and [HOSTING.md](HOSTING.md) for Cloud Run, Lambda,
Cloudflare Containers, servers, Terraform, and the deployment CLI.

## Supported documents

| Document | Key fields extracted | Identifier validation |
|---|---|---|
| Passport (biodata) | name, passport no., nationality, DOB, sex, expiry/issue dates, place of birth | TD3 MRZ ICAO check digits |
| Passport (back page) | father/mother/spouse, address, file no., old passport details | — |
| PAN card | PAN, name, father's name, DOB | PAN format + holder-type char |
| Aadhaar (front/back) | Aadhaar no. (+ VID, masked-card support), name, DOB/YOB, gender, address, pincode | Verhoeff checksum |
| Driving licence | DL no., name, DOB, issue/validity dates (NT + TR), address, blood group, vehicle class | DL format |
| Voter ID (EPIC) | EPIC no., name, relation name + type, gender, DOB/age | EPIC format |
| MGNREGA/NREGA job card | job-card no., household head, registration/validity, location, category/BPL, adult members | Conservative hierarchical format |
| NPR name/address letter | reference no., resident name, address, pincode, issue date | Not offline-verifiable |

Together with the existing passport path, this covers the officially valid
document categories listed in the
[RBI KYC Master Direction](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=11566);
PAN is supported as a separate tax identifier.

The document type is detected automatically; `/scan` returns the matching
field block (`fields`/`backPageFields` for passports, or `panFields`,
`aadhaarFields`, `drivingLicenceFields`, `voterIdFields`,
`nregaJobCardFields`, or `nprLetterFields`) keyed by `documentType`.

NREGA and NPR support is experimental until measured against a representative
private image dataset. The extraction layer handles multiple label/layout
variants, but deterministic text-region tests are not evidence of real-image
accuracy.

Country/document hints route through full-page classification rather than relying
on an ambiguous passport crop. New structured-document evidence can also override
generic passport-like labels. Unknown or conflicting document hints fail explicitly.

## Quickstart

### Python

Requires Python 3.12+ and [`uv`](https://github.com/astral-sh/uv).

```bash
make install
make dev          # uvicorn on :8000 with reload
```

Scan a document:

```bash
curl -F image=@/path/to/document.jpg \
  http://localhost:8000/scan
```

### Docker

```bash
make docker-build
docker run --rm -p 8000:8000 passport-ocr
```

The image pre-downloads PP-OCRv5 models at build time so the first request is fast.

### Node.js (npm package)

```bash
npm install document-ocr
```

```ts
import { DocumentOCR } from 'document-ocr';

const ocr = new DocumentOCR();
const result = await ocr.scan(imageBuffer);

if (result.status === 'success' && result.documentType === 'passport') {
  console.log(result.fields.passportNumber, result.mrzValid);
}
await ocr.stop();
```

The package auto-creates a `.venv`, installs the Python deps, and manages the local server lifecycle. See [`packages/passport-ocr/README.md`](packages/passport-ocr/README.md) for full options including HTTP mode.

## HTTP API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | `503` until OCR models finish loading |
| GET | `/documents` | Document profiles and runtime capabilities |
| POST | `/scan` | Single scan with country/document hints and optional evidence |
| POST | `/scan/batch` | Independent inputs, preserving order |
| POST | `/scan/document` | Grouped front/back images or all PDF pages, with conflict detection |
| GET | `/review` | Browser review, corrections and export |
| POST | `/preview`, `/redact` | Normalized preview or selected raster redactions |
| POST | `/jobs` | Optional persistent-server queue |
| GET / DELETE | `/jobs/{id}` | Poll or delete a retained job |

`/scan` accepts images and PDFs up to 10 MB. Concurrency is serialized
internally. Set `API_TOKEN` to require
`Authorization: Bearer <token>` on document and job endpoints. For internet-facing deployments,
use platform IAM or an API gateway in addition to application-level controls.
Incomplete or semantically invalid non-passport extractions return HTTP `422`
with the full structured failure result.

## Output

```jsonc
{
  "status": "success",                  // success | failure | unsupported_page
  "documentType": "passport",           // passport | pan | aadhaar | driving_licence | voter_id | nrega_job_card | npr_letter | unknown
  "pageType": "passport_biodata",       // same document values, plus passport_biodata | passport_non_biodata | unknown
  "confidence": 0.91,
  "fields": {
    "surname": "...", "givenNames": "...", "fullName": "...",
    "passportNumber": "...", "nationality": "IND",
    "dateOfBirth": "1990-05-21", "sex": "M",
    "expiryDate": "2030-04-12", "issueDate": "2020-04-13",
    "placeOfBirth": "...", "countryCode": "IND"
  },
  "backPageFields": {
    "fatherName": "...", "motherName": "...", "spouseName": "...",
    "address": "...", "pincode": "...", "city": "...", "state": "...",
    "fileNumber": "...", "oldPassportNumber": "...",
    "oldPassportDateOfIssue": "...", "oldPassportPlaceOfIssue": "..."
  },
  // Exactly one document block is populated, keyed by documentType; the rest
  // are null. (passport uses fields/backPageFields above.)
  "panFields":            { "panNumber": "...", "name": "...", "fatherName": "...", "dateOfBirth": "..." },
  "aadhaarFields":        { "aadhaarNumber": "...", "name": "...", "dateOfBirth": "...", "yearOfBirth": null,
                            "gender": "...", "address": "...", "pincode": "...", "checksumValid": true,
                            "aadhaarMasked": false, "aadhaarLast4": "...", "vid": null },
  "drivingLicenceFields": { "dlNumber": "...", "name": "...", "dateOfBirth": "...", "issueDate": "...",
                            "validityDate": "...", "address": "...", "relationName": "...", "bloodGroup": "...",
                            "classOfVehicle": "...", "validityDateTransport": null },
  "voterIdFields":        { "epicNumber": "...", "name": "...", "relationName": "...", "relationType": "father",
                            "gender": "...", "dateOfBirth": "...", "age": null },
  "nregaJobCardFields":   { "jobCardNumber": "...", "headOfHousehold": "...", "category": "SC",
                            "registrationDate": "...", "validityFrom": "...", "validityTo": "...",
                            "address": "...", "village": "...", "gramPanchayat": "...", "block": "...",
                            "district": "...", "state": "...", "bplStatus": true, "familyId": "...",
                            "members": [{ "serialNumber": "1", "name": "...",
                                          "fatherOrHusbandName": "...", "gender": "FEMALE", "age": 39 }] },
  "nprLetterFields":      { "referenceNumber": "...", "name": "...", "address": "...",
                            "pincode": "...", "issueDate": "..." },
  "mrzRaw": ["P<IND...", "..."], "mrzValid": true,
  "lowConfidence": false,
  "identifierValid": null,              // format/checksum only; never an authenticity verdict
  "missingRequiredFields": [],
  "errors": [], "warnings": [],
  "processingMs": 412
}
```

## Pipeline

1. `preprocess` — orientation, document boundary detection, perspective correction, quality checks
2. `classify_passport_page` — biodata vs non-biodata vs not-a-passport (cheap bottom-crop probe)
3. passport path: `run_ocr` (RapidOCR PP-OCRv5, full-page enrichment and visual cross-checks even when the cropped MRZ is valid) → `parse_mrz` (TD3 MRZ with per-field + overall checksum validation) → `extract_back_page` (bilingual label-aware extraction) → `validate` (cross-checks MRZ vs visual fields, computes confidence)
4. non-passport path: `classify_document` routes full-page OCR to the matching
   extractor (`pan` / `aadhaar` / `driving_licence` / `voter_id` /
   `nrega_job_card` / `npr_letter`), checks minimum required fields, validates
   identifiers where possible, and fails closed on partial or semantically
   implausible records

For non-passport documents, `status: "success"` means the extractor returned
the document-specific minimum field set and passed a conservative OCR-region
confidence gate. Alternate model readings for the same detected geometry count
once. `identifierValid` means only an offline format/checksum check passed. NPR
references have no universal public checksum, so this value is `null`; it is
never evidence of authenticity.

### Non-passport OCR languages

The default recognition behavior is unchanged (`en`, with the existing
automatic fallback). If the expected KYC population uses a known script, run
up to four recognition passes only on the non-passport path:

```bash
DOCUMENT_OCR_KYC_LANGS=en,devanagari make dev
```

Available values are `en`, `latin`, `devanagari`, `ka` (Kannada), `ta`
(Tamil), and `te` (Telugu). Extra models increase latency and memory. The
bundled RapidOCR version has no Bengali recognition model: Bengali-labelled
extractor fixtures prove parsing behavior only, not Bengali image OCR. Select
languages and release thresholds from measured benchmark slices. Server
readiness initializes every configured model so model-download or startup
failures are reported before the first scan. Unsupported names or more than
four configured models fail readiness instead of silently falling back.

Single entry point: `core.pipeline.scan(image_input)`.

### Verification

Run `make test` for Python and SDK regressions, and `make smoke` for a real-model
check against two generated, clearly synthetic documents. The smoke check
requires the OCR models and is separate from the offline unit suite. It is not
a representative accuracy measurement.

Use `make benchmark` with a private passport manifest following
[`benchmarks/PASSPORT_DATASET.md`](benchmarks/PASSPORT_DATASET.md), or
`make benchmark-kyc KYC_MANIFEST=/secure/path/manifest.json` following
[`benchmarks/KYC_DATASET.md`](benchmarks/KYC_DATASET.md), to measure actual image
accuracy. Missing required coverage fails the release gates.

See [`AUDIT.md`](AUDIT.md) for the September 2026 review, verified fixes,
synthetic before/after results, and remaining accuracy work.

## Deployment

The same pipeline runs as a container, on Cloud Run, or on AWS Lambda. Copy
`.env.deploy.example` to `.env.deploy.<env>` and fill in the relevant values
first (Docker Hub and/or GCP).

Cloud Run and Lambda deployments are authenticated by default. Do not expose
an identity-document endpoint publicly without authentication, authorization,
rate limiting, encrypted transport, and an explicit data-retention policy.

### Cloud Run (recommended)

```bash
# Build deploy/docker/Dockerfile, push to Artifact Registry, deploy the service.
bash deploy/cloudrun/deploy.sh production
# or via Cloud Build:
gcloud builds submit --config deploy/cloudrun/cloudbuild.yaml \
  --substitutions=_REGION=asia-south1,_SERVICE=document-ocr
```

Service config lives in [`deploy/cloudrun/service.yaml`](deploy/cloudrun/service.yaml)
(2 GiB / 2 vCPU, `containerConcurrency: 1` since OCR is serialized, scale-to-zero).

### AWS Lambda (container image)

The SDK's `mode: 'lambda'` invokes a function that takes `{ "image_base64": "..." }`.

```bash
cd deploy/lambda
sam build && sam deploy --guided   # uses Dockerfile.lambda + template.yaml
```

The handler ([`deploy/lambda/handler.py`](deploy/lambda/handler.py)) returns the
raw scan result on success and an `{statusCode, body}` envelope for errors.
The included SAM template supports IAM-authenticated direct invocation and does
not create a public API Gateway endpoint.

## Tests & benchmarks

```bash
make test
make build
```

The per-document extractors are covered by deterministic `TextRegion` fixtures
under `tests/python/test_*_extractor.py`. These tests verify parsing and
validation behavior; they are not a claim of real-world OCR accuracy.

For the legacy passport image benchmark, place its private dataset and
`manifest.json` under `benchmark-data/` and run:

```bash
make benchmark
```

For a non-passport KYC dataset, use the versioned manifest and release gates:

```bash
make benchmark-kyc \
  KYC_MANIFEST=/secure/kyc-eval/manifest.json \
  KYC_DATASET_ROOT=/secure/kyc-eval \
  KYC_REPORT=/secure/kyc-eval/reports/main.json
```

The KYC evaluator reports classification, acceptance/false-success,
exact/normalized field, complete-record, runtime, per-document, and
design/year/issuer/language/capture-quality slice metrics without copying
ground-truth values into its report. Required per-document slices fail manifest
validation when a declared variant is absent. See
[`benchmarks/KYC_DATASET.md`](benchmarks/KYC_DATASET.md) for the variant matrix
and annotation workflow.

`benchmark-data/` is ignored by Git. Never commit identity documents or
personal data. See [CONTRIBUTING.md](CONTRIBUTING.md) for fixture rules.

For public datasets, see [the linked catalog and fixed 40-case evaluation
sample](benchmarks/PUBLIC_DATASETS.md). The bounded fetcher downloads only selected
images and labels, with pinned checksums. Integrity checks are separate from OCR accuracy;
see the [measured OCR baseline](benchmarks/PUBLIC_BASELINE.md) for current accuracy
and failures. Further profiles need reviewed adapters before entering accuracy gates.

## Privacy and security

Local Python and npm-local modes process documents on the same machine and do
not include telemetry or document storage. HTTP and Lambda modes transmit
documents to infrastructure controlled by the operator.

Read [PRIVACY.md](PRIVACY.md) before deploying and report vulnerabilities using
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Dependencies retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
