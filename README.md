# document-ocr

High-accuracy OCR pipeline for passports and Indian KYC documents. Preprocesses scans, classifies the document, runs targeted OCR with RapidOCR (PP-OCRv5), and extracts structured fields — passport MRZ with ICAO checksum validation, passport back-page fields (parents, address, old passport number), and the identifier + holder fields for PAN, Aadhaar, driving licence, and voter ID cards.

Ships as a Python package with a FastAPI server, plus an npm wrapper at [`packages/passport-ocr`](packages/passport-ocr) that auto-spawns the Python server for Node.js consumers.

## Supported documents

| Document | Key fields extracted | Identifier validation |
|---|---|---|
| Passport (biodata) | name, passport no., nationality, DOB, sex, expiry/issue dates, place of birth | TD3 MRZ ICAO check digits |
| Passport (back page) | father/mother/spouse, address, file no., old passport details | — |
| PAN card | PAN, name, father's name, DOB | PAN format + holder-type char |
| Aadhaar (front/back) | Aadhaar no. (+ VID, masked-card support), name, DOB/YOB, gender, address, pincode | Verhoeff checksum |
| Driving licence | DL no., name, DOB, issue/validity dates (NT + TR), address, blood group, vehicle class | DL format |
| Voter ID (EPIC) | EPIC no., name, relation name + type, gender, DOB/age | EPIC format |

The document type is detected automatically; `/scan` returns the matching field block (`fields`/`backPageFields` for passports, `panFields`/`aadhaarFields`/`drivingLicenceFields`/`voterIdFields` for the others) keyed by `documentType`.

## Quickstart

### Python

Requires Python 3.12+ and [`uv`](https://github.com/astral-sh/uv).

```bash
make install
make dev          # uvicorn on :8000 with reload
```

Scan a passport image:

```bash
curl -F image=@sample-passports/sample-indian-passport-1.jpg \
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

if (result.status === 'success') {
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
| POST | `/scan` | Multipart image upload, returns scan result JSON |

`/scan` accepts images and PDFs up to 10 MB. Concurrency is serialized internally.

## Output

```jsonc
{
  "status": "success",                  // success | failure | unsupported_page
  "documentType": "passport",
  "pageType": "passport_biodata",       // passport_biodata | passport_non_biodata | unknown
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
  "mrzRaw": ["P<IND...", "..."], "mrzValid": true,
  "lowConfidence": false,
  "errors": [], "warnings": [],
  "processingMs": 412
}
```

## Pipeline

1. `preprocess` — orientation, document boundary detection, perspective correction, quality checks
2. `classify_passport_page` — biodata vs non-biodata vs not-a-passport (cheap bottom-crop probe)
3. passport path: `run_ocr` (RapidOCR PP-OCRv5, full-page fallback when MRZ is missing) → `parse_mrz` (TD3 MRZ with per-field + overall checksum validation) → `extract_back_page` (bilingual label-aware extraction) → `validate` (cross-checks MRZ vs visual fields, computes confidence)
4. non-passport path: `classify_document` routes full-page OCR to the matching extractor (`pan` / `aadhaar` / `driving_licence` / `voter_id`), validating each document's identifier (PAN format, Verhoeff for Aadhaar, EPIC/DL format)

Single entry point: `core.pipeline.scan(image_input)`.

## Deployment

The same pipeline runs as a container, on Cloud Run, or on AWS Lambda. Copy
`.env.deploy.example` to `.env.deploy.<env>` and fill in the relevant values
first (Docker Hub and/or GCP).

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

## Tests & benchmarks

```bash
make test                  # python + ts unit suites (fixture-driven, fast)
make benchmark             # passport accuracy on sample-passports/
make benchmark-documents   # end-to-end KYC accuracy (clean + degraded)
make gen-documents         # regenerate the labelled synthetic KYC images
```

`benchmark-documents` runs the whole pipeline (image → OCR → fields) on the
labelled synthetic dataset under [`sample-documents/`](sample-documents), scoring
each image against ground truth under a sweep of degradations (blur / rotate /
noise / JPEG / low-res). Clean images route + extract at 100%; the report breaks
down accuracy by document type and degradation so robustness regressions surface.

## License

MIT
