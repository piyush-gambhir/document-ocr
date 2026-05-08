# document-ocr

High-accuracy passport OCR pipeline. Preprocesses scans, classifies the page, runs targeted OCR with RapidOCR (PP-OCRv5), parses the MRZ with checksum validation, and extracts back-page fields (parents, address, old passport number) for Indian passports.

Ships as a Python package with a FastAPI server, plus an npm wrapper at [`packages/passport-ocr`](packages/passport-ocr) that auto-spawns the Python server for Node.js consumers.

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
2. `classify_passport_page` — biodata vs non-biodata vs unsupported
3. `run_ocr` — RapidOCR PP-OCRv5 against targeted crop, with full-page fallback when MRZ is missing
4. `parse_mrz` — TD3 MRZ parsing with per-field and overall checksum validation
5. `extract_back_page` — bilingual label-aware field extraction for Indian back pages
6. `validate` — cross-checks MRZ against visual fields, computes overall confidence

Single entry point: `core.pipeline.scan(image_input)`.

## Tests & benchmarks

```bash
make test         # python + ts suites
make benchmark    # accuracy on sample-passports/
```

## License

MIT
