# document-ocr

Standalone document OCR for Node.js, optimized for passport biodata pages. Extracts MRZ data, passport fields, and classifies unsupported passport pages without requiring an external service.

`DocumentOCR` is the primary v2 API. `PassportOCR` remains available as a compatibility alias.

## Install

```bash
npm install document-ocr
```

**Prerequisites:** Python 3.12+ must be installed on your machine. The postinstall script automatically creates a virtual environment and installs PaddleOCR.

## Quick Start

```typescript
import { DocumentOCR } from 'document-ocr'

const ocr = new DocumentOCR()
const result = await ocr.scan(imageFile)

if (result.status === 'success') {
  console.log(result.fields.surname)
  console.log(result.fields.passportNumber)
  console.log(result.fields.dateOfBirth)
  console.log(result.mrzValid)
}

if (result.status === 'unsupported_page') {
  console.log(result.pageType)          // 'passport_non_biodata'
  console.log(result.unsupportedReason) // 'NON_BIODATA_PAGE'
}

await ocr.stop()
```

## How It Works

```
npm install document-ocr
  │
  └── postinstall:
      1. Finds Python 3.12+
      2. Creates .venv inside the package
      3. Installs PaddleOCR + dependencies

ocr.scan(image)
  │
  └── First call:
      1. Auto-starts a local Python server
      2. Loads OCR models
      3. Runs a fast page classifier
      4. Either:
         - extracts passport biodata fields and MRZ, or
         - returns an unsupported-page result

      Subsequent calls:
      1. Reuses the running server
      2. Reuses warmed OCR models
```

## Modes

### Local Mode (default)

```typescript
const ocr = new DocumentOCR()
const result = await ocr.scan(image)
await ocr.stop()
```

### HTTP Mode

```typescript
const ocr = new DocumentOCR({
  mode: 'http',
  endpoint: 'https://your-ocr-service.example.com',
})
```

### Lambda Mode

```typescript
const ocr = new DocumentOCR({
  mode: 'lambda',
  functionName: 'document-ocr-prod',
})
```

## API

### `new DocumentOCR(options?)`

| Option | Type | Default | Description |
|---|---|---|---|
| `mode` | `'local' \| 'http' \| 'lambda'` | `'local'` | Invocation mode |
| `endpoint` | `string` | — | Required for `'http'` mode |
| `functionName` | `string` | — | Required for `'lambda'` mode |
| `timeoutMs` | `number` | `30000` | Request timeout (ms) |
| `retries` | `number` | `2` | Retry count with exponential backoff |
| `apiKey` | `string` | — | Optional Bearer token for HTTP mode |

### `ocr.scan(image): Promise<DocumentScanResult>`

| Input type | Example |
|---|---|
| `File` | From `<input type="file">` |
| `Blob` | From fetch response |
| `Buffer` | `fs.readFileSync('passport.jpg')` |
| `ArrayBuffer` | Raw bytes |
| `string` (base64) | `"iVBORw0KGgo..."` |
| `string` (URL) | `"https://example.com/passport.jpg"` |

### `ocr.stop(): Promise<void>`

Stops the local Python server. Call when done to free resources.

### `DocumentScanResult`

```typescript
type DocumentScanResult =
  | {
      status: 'success'
      documentType: 'passport'
      pageType: 'passport_biodata'
      confidence: number
      lowConfidence: boolean
      fields: {
        surname: string | null
        givenNames: string | null
        fullName: string | null
        passportNumber: string | null
        nationality: string | null
        dateOfBirth: string | null
        sex: 'M' | 'F' | 'X' | null
        expiryDate: string | null
        issueDate: string | null
        placeOfBirth: string | null
        countryCode: string | null
      }
      mrzRaw: [string, string] | null
      mrzValid: boolean
      unsupportedReason: null
      probeText: string[]
      errors: string[]
      warnings: string[]
      processingMs: number
    }
  | {
      status: 'unsupported_page'
      documentType: 'passport' | 'unknown'
      pageType: 'passport_non_biodata' | 'unknown'
      confidence: number
      lowConfidence: boolean
      fields: null
      mrzRaw: null
      mrzValid: boolean
      unsupportedReason: 'NON_BIODATA_PAGE' | 'UNSUPPORTED_DOCUMENT'
      probeText: string[]
      errors: string[]
      warnings: string[]
      processingMs: number
    }
  | {
      status: 'failure'
      documentType: 'passport' | 'unknown'
      pageType: 'passport_biodata' | 'unknown'
      confidence: number
      lowConfidence: boolean
      fields: PassportFields | null
      mrzRaw: [string, string] | null
      mrzValid: boolean
      unsupportedReason: null
      probeText: string[]
      errors: string[]
      warnings: string[]
      processingMs: number
    }
```

## Benchmark Gates

The Python benchmark reads fixture expectations from `sample-passports/manifest.json` and enforces these vNext targets:

- Warm passport biodata median latency at or below 5000ms
- Passport biodata field accuracy at or above 97%
- MRZ exact-match rate at or above 99%
- Non-biodata passport-page classification accuracy at or above 95%

Run it with:

```bash
uv run python benchmarks/accuracy.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `PASSPORT_OCR_SKIP_PYTHON=1` | Skip Python setup during postinstall |

## Error Handling

```typescript
const result = await ocr.scan(image)

if (result.status === 'failure') {
  if (result.errors.includes('IMAGE_TOO_BLURRY')) {
    // Ask user to retake with better focus
  }
  if (result.errors.includes('RESOLUTION_TOO_LOW')) {
    // Image too small
  }
  if (result.lowConfidence && result.fields) {
    console.log(result.fields) // partial extraction
  }
}
```

## License

MIT
