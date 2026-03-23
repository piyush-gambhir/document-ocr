# passport-ocr

TypeScript client for high-accuracy passport OCR. Extracts MRZ data, personal details, and validates checksums using PaddleOCR v3.

## Install

```bash
npm install passport-ocr
```

## Quick Start

```typescript
import { PassportOCR } from 'passport-ocr'

const ocr = new PassportOCR({
  endpoint: 'https://your-ocr-service.example.com',
})

const result = await ocr.scan(imageFile) // File | Buffer | base64 | URL

if (result.success) {
  console.log(result.fields.surname)       // 'KUMAR'
  console.log(result.fields.passportNumber) // 'J8369854'
  console.log(result.fields.dateOfBirth)    // '1990-03-15'
  console.log(result.mrzValid)              // true
  console.log(result.confidence)            // 0.95
}

if (result.lowConfidence) {
  // 0.3 <= confidence < 0.7 — prompt user to retake photo
}
```

## API

### `new PassportOCR(options)`

| Option | Type | Default | Description |
|---|---|---|---|
| `endpoint` | `string` | — | **Required (HTTP mode).** URL of the OCR service |
| `mode` | `'http' \| 'lambda'` | `'http'` | Invocation mode |
| `functionName` | `string` | — | **Required (Lambda mode).** AWS Lambda function name |
| `timeoutMs` | `number` | `30000` | Request timeout in milliseconds |
| `retries` | `number` | `2` | Retry count with exponential backoff |
| `apiKey` | `string` | — | Optional Bearer token for HTTP mode |

### `ocr.scan(image): Promise<PassportScanResult>`

Accepts any image input:

| Input type | Example |
|---|---|
| `File` | From `<input type="file">` |
| `Blob` | From fetch response |
| `Buffer` | Node.js buffer |
| `ArrayBuffer` | Raw bytes |
| `string` (base64) | `"iVBORw0KGgo..."` |
| `string` (URL) | `"https://example.com/passport.jpg"` |

### `PassportScanResult`

```typescript
{
  success: boolean          // true if confidence >= 0.7 and fields extracted
  confidence: number        // 0.0 - 1.0
  lowConfidence: boolean    // true when 0.3 <= confidence < 0.7
  fields: {
    surname: string | null
    givenNames: string | null
    fullName: string | null
    passportNumber: string | null
    nationality: string | null
    dateOfBirth: string | null    // ISO 8601 (YYYY-MM-DD)
    sex: 'M' | 'F' | 'X' | null
    expiryDate: string | null     // ISO 8601
    issueDate: string | null
    placeOfBirth: string | null
    countryCode: string | null    // ISO 3166-1 alpha-3
  }
  mrzRaw: [string, string] | null  // Raw MRZ lines
  mrzValid: boolean                 // All ICAO checksums passed
  errors: string[]
  warnings: string[]
  processingMs: number
}
```

## Deploying the OCR Service

This SDK is a client — it needs a running [passport-ocr](https://github.com/piyush-gambhir/passport-ocr) service.

### Local (Docker)

```bash
git clone https://github.com/piyush-gambhir/passport-ocr
cd passport-ocr
docker build -f deploy/docker/Dockerfile -t passport-ocr .
docker run -p 8000:8000 passport-ocr
```

Then use `endpoint: 'http://localhost:8000'`.

### Production (Railway / Fly.io / ECS)

Deploy the Docker image to any container platform. The service exposes:

- `GET /health` — liveness check (always 200)
- `GET /ready` — readiness check (200 after models loaded, 503 during startup)
- `POST /scan` — passport OCR endpoint (multipart/form-data)

### Server Features

- PaddleOCR v3 with ICAO MRZ parsing and digit correction
- Concurrency protection (1 OCR at a time via semaphore)
- 30-second request timeout
- Eager model loading on startup
- 10MB upload limit

## Error Handling

```typescript
const result = await ocr.scan(image)

if (!result.success) {
  if (result.errors.includes('IMAGE_TOO_BLURRY')) {
    // Ask user to retake with better focus
  }
  if (result.errors.includes('RESOLUTION_TOO_LOW')) {
    // Image too small (< 600px shortest dimension)
  }
  if (result.lowConfidence) {
    // Data was extracted but unreliable — show for manual review
    console.log(result.fields) // partially extracted fields
  }
}
```

## Lambda Mode

For AWS Lambda deployment (direct invocation, no HTTP):

```typescript
const ocr = new PassportOCR({
  mode: 'lambda',
  functionName: 'passport-ocr-prod',
})

// Usage is identical
const result = await ocr.scan(imageBuffer)
```

Requires `@aws-sdk/client-lambda` as a peer dependency.

## License

MIT
