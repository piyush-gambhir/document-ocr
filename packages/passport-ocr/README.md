# passport-ocr

Standalone passport OCR for Node.js. Extracts MRZ data, personal details, and validates ICAO checksums. No external server setup needed — Python + PaddleOCR v3 is managed automatically.

## Install

```bash
npm install passport-ocr
```

**Prerequisites:** Python 3.12+ must be installed on your machine. The postinstall script automatically creates a virtual environment and installs PaddleOCR.

## Quick Start

```typescript
import { PassportOCR } from 'passport-ocr'

const ocr = new PassportOCR()  // local mode — no server URL needed
const result = await ocr.scan(imageFile)

if (result.success) {
  console.log(result.fields.surname)       // 'KUMAR'
  console.log(result.fields.passportNumber) // 'J8369854'
  console.log(result.fields.dateOfBirth)    // '1990-03-15'
  console.log(result.mrzValid)              // true
  console.log(result.confidence)            // 0.95
}

// Clean up when done
await ocr.stop()
```

## How It Works

```
npm install passport-ocr
  │
  └── postinstall:
      1. Finds Python 3.12+
      2. Creates .venv inside the package
      3. Installs PaddleOCR + dependencies

ocr.scan(image)
  │
  └── First call:
      1. Auto-starts a local Python server
      2. Downloads OCR models (~500MB, one-time)
      3. Sends image to local server
      4. Returns structured result

      Subsequent calls:
      1. Reuses running server
      2. ~2-15s per image
```

## Modes

### Local Mode (default) — standalone, no setup

```typescript
const ocr = new PassportOCR()
const result = await ocr.scan(image)
await ocr.stop()  // clean up
```

### HTTP Mode — connect to a deployed server

```typescript
const ocr = new PassportOCR({
  mode: 'http',
  endpoint: 'https://your-ocr-service.example.com',
})
```

### Lambda Mode — AWS Lambda direct invocation

```typescript
const ocr = new PassportOCR({
  mode: 'lambda',
  functionName: 'passport-ocr-prod',
})
```

## API

### `new PassportOCR(options?)`

| Option | Type | Default | Description |
|---|---|---|---|
| `mode` | `'local' \| 'http' \| 'lambda'` | `'local'` | Invocation mode |
| `endpoint` | `string` | — | Required for `'http'` mode |
| `functionName` | `string` | — | Required for `'lambda'` mode |
| `timeoutMs` | `number` | `30000` | Request timeout (ms) |
| `retries` | `number` | `2` | Retry count with exponential backoff |
| `apiKey` | `string` | — | Optional Bearer token for HTTP mode |

### `ocr.scan(image): Promise<PassportScanResult>`

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

### `PassportScanResult`

```typescript
{
  success: boolean          // true if confidence >= 0.7
  confidence: number        // 0.0 - 1.0
  lowConfidence: boolean    // true when 0.3 <= confidence < 0.7
  fields: {
    surname: string | null
    givenNames: string | null
    fullName: string | null
    passportNumber: string | null
    nationality: string | null
    dateOfBirth: string | null    // YYYY-MM-DD
    sex: 'M' | 'F' | 'X' | null
    expiryDate: string | null     // YYYY-MM-DD
    issueDate: string | null
    placeOfBirth: string | null
    countryCode: string | null    // ISO 3166-1 alpha-3
  }
  mrzRaw: [string, string] | null
  mrzValid: boolean
  errors: string[]
  warnings: string[]
  processingMs: number
}
```

## Docker / Cloud Run

When deploying in Docker, add Python to your image:

```dockerfile
# Add to your existing Dockerfile
RUN apt-get update && apt-get install -y python3 python3-venv python3-pip
# npm install will run postinstall automatically
```

## Environment Variables

| Variable | Description |
|---|---|
| `PASSPORT_OCR_SKIP_PYTHON=1` | Skip Python setup during postinstall |

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
    // Data extracted but unreliable
    console.log(result.fields) // partially extracted
  }
}
```

## License

MIT
