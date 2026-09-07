# document-ocr

Document OCR for Node.js, with a bundled local Python/RapidOCR runtime and
HTTP/Lambda clients. It extracts structured fields from passports, Indian and
experimental US identity, immigration and tax documents. The server
catalog reports each family’s required fields and experimental status.

> This is beta extraction software. It does not verify document authenticity,
> detect fraud, query issuing authorities, or by itself satisfy KYC obligations.
> NREGA and NPR extraction is experimental until measured against a
> representative private image dataset.

## Install

```bash
npm install document-ocr
```

Python 3.12 or 3.13 is required. If [`uv`](https://docs.astral.sh/uv/) is
available, the postinstall script can create the local environment
automatically.

## Local mode

```typescript
import { DocumentOCR } from 'document-ocr'

const ocr = new DocumentOCR()
const result = await ocr.scan(imageBuffer)

if (result.status === 'success') {
  switch (result.documentType) {
    case 'passport':
      console.log(result.fields?.passportNumber)
      break
    case 'pan':
      console.log(result.panFields?.panNumber)
      break
    case 'aadhaar':
      console.log(result.aadhaarFields?.aadhaarLast4)
      break
    case 'nrega_job_card':
      console.log(result.nregaJobCardFields?.jobCardNumber)
      break
    case 'npr_letter':
      console.log(result.nprLetterFields?.referenceNumber)
      break
  }
}

await ocr.stop()
```

Local mode starts the bundled FastAPI process on `127.0.0.1`, reuses it across
scans, and stops it when `ocr.stop()` is called. Documents stay on the local
machine.

`PassportOCR` remains available as a compatibility alias for `DocumentOCR`.

For non-passport results, `status: 'success'` requires the document-specific
minimum fields and a conservative OCR-region confidence gate.
`identifierValid` reports only a local format/checksum check, not authenticity;
`missingRequiredFields` explains partial failures. In HTTP mode these
structured partial results use status `422` and are returned by the client
rather than thrown.

Set `DOCUMENT_OCR_KYC_LANGS=en,devanagari` (or `latin`, `ka`, `ta`, `te`) to
run known recognition models on the non-passport path. Each additional model
adds latency and memory, so choose the list from measured language slices.
Unsupported names or more than four models fail server readiness.

## Other modes

### HTTP

```typescript
const ocr = new DocumentOCR({
  mode: 'http',
  endpoint: 'https://ocr.example.com',
  apiKey: process.env.API_TOKEN,
})
```

`apiKey` is sent as a Bearer token. The included Python server enforces it when
`API_TOKEN` is configured.

### AWS Lambda

```typescript
const ocr = new DocumentOCR({
  mode: 'lambda',
  functionName: 'document-ocr-prod',
})
```

Lambda mode uses IAM-authenticated direct invocation through the AWS SDK.

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `mode` | `local \| http \| lambda` | `local` | Invocation mode |
| `endpoint` | `string` | — | Required in HTTP mode |
| `functionName` | `string` | — | Required in Lambda mode |
| `timeoutMs` | `number` | `30000` | Per-attempt timeout |
| `retries` | `number` | `2` | Retry count |
| `apiKey` | `string` | — | Bearer token for HTTP mode |
| `authHeaders` | `(url, signal) => HeadersInit \| Promise<HeadersInit>` | — | Per-attempt HTTP credentials |

Accepted image inputs are `File`, `Blob`, `Buffer`, `ArrayBuffer`, base64
strings, and HTTP(S) URLs.

Set `PASSPORT_OCR_SKIP_PYTHON=1` during installation to skip local Python setup
when only HTTP or Lambda mode is required.

## Privacy

HTTP and Lambda modes transmit identity documents to the configured
infrastructure. Protect the endpoint, avoid logging extracted personal data,
and define an appropriate retention policy. Never submit real identity
documents to public issues or test fixtures.

## License

[MIT](LICENSE)

## Document hints, evidence, and multiple pages

```typescript
const options = { documentType: 'us_driver_license', country: 'USA', includeEvidence: true }
const result = await ocr.scan(imageBuffer, options)
console.log(result.documentFields, result.fieldEvidence, result.checks)

// Independent documents, with one result per input.
const batch = await ocr.scanBatch([firstImage, secondImage], options)

// Front/back images or a PDF belonging to one document.
const document = await ocr.scanDocument([frontImage, backImage], options)
console.log(document.documentFields, document.conflicts)

const catalog = await ocr.documents()
console.log(catalog.documents, catalog.capabilities)
```

The catalog reports supported families, required fields, available extraction
sources, and experimental status. New families include US driver licences and
state IDs, passport cards, green cards, EADs, visas, I-94s and W-9s. These profiles
remain experimental. Bank statements, utility bills, payslips and Indian business
records are planned, not implemented profiles.
Support and required fields are defined by the server catalog; extraction does
not establish document authenticity.

`documentFields`, `issuingCountry`, `issuingRegion`, `fieldEvidence`, `checks`,
and `schemaVersion` extend the result without replacing legacy field blocks.
Evidence contains source text, bounding boxes, source type, confidence, and an
optional page number. Include it only when needed because it contains document
values. Grouped results expose conflicting page values in `conflicts` with
1-based page numbers. Batch/group/catalog methods use local or HTTP mode.

## Short-lived HTTP credentials

Provide an asynchronous `authHeaders` callback to refresh headers on every
attempt. It receives the request URL and attempt abort signal. Returned headers
override the static `apiKey` header, which otherwise remains a fallback.

For Cloud Run IAM, install `google-auth-library` in the application and obtain
an audience-matched ID-token client using Application Default Credentials, as
described in the [Google Auth Library documentation](https://github.com/googleapis/google-auth-library-nodejs#working-with-id-tokens):

```typescript
import { GoogleAuth } from 'google-auth-library'

const endpoint = 'https://your-private-service.run.app'
const identity = await new GoogleAuth().getIdTokenClient(endpoint)
const ocr = new DocumentOCR({
  mode: 'http',
  endpoint,
  authHeaders: async () => {
    const headers = await identity.getRequestHeaders()
    return { Authorization: headers.get('authorization')! }
  },
})
```

The caller needs Cloud Run Invoker permission. API bearer-token authentication
on your own server continues to use `apiKey`.

## Larger Lambda documents

```typescript
const result = await ocr.scanS3({
  bucket: 'private-document-inputs',
  key: 'uploads/opaque-sample.pdf',
  versionId: 'optional-object-version',
}, { documentType: 'us_w9', country: 'USA' })
```

`scanS3` requires Lambda mode. The Lambda deployment restricts readable S3
buckets/prefixes and its execution role must be authorized to read the object.
Direct image invocations count the exact UTF-8 JSON payload, including base64
and options, against Lambda's 6 MiB synchronous request ceiling. Oversized
requests and invalid local input fail immediately without retries; use S3 for
larger images. Transient transport errors retain per-attempt retry/timeouts.

## Scaffold and deploy a service

```bash
DOCUMENT_OCR_SKIP_PYTHON=1 npx document-ocr init --target cloudrun --directory my-ocr --project YOUR_PROJECT
cd my-ocr
npx document-ocr doctor
npx document-ocr deploy --dry-run
npx document-ocr deploy
```

Targets are `cloudrun`, `lambda`, `cloudflare`, and `server`. Initialization
copies the versioned Python source, dependency lock, deployment templates,
and Terraform templates into the chosen directory and writes `dococr.json`.
It refuses to replace existing paths. `deploy --dry-run` prints the wrapper
command without contacting a provider; `deploy` executes that wrapper.

`dococr.json` stores nonsecret deployment settings: target, service name,
`economy`/`warm` profile, OCR languages, and optional project, region, image,
domain, bucket, and prefix. Credentials stay in your environment/provider CLI.
Cloud Run uses `GCP_PROJECT` and optional `GCP_REGION`; Lambda uses `AWS_REGION`
and optional S3 scope; server hosting requires `DOMAIN` and `API_TOKEN`.
Cloudflare uses its logged-in Wrangler account and separately configured
`API_TOKEN` secret. See the scaffolded `HOSTING.md` for provider-specific setup.

`doctor` checks local CLI/config prerequisites. Add `--endpoint URL` for a
liveness request to `/health`, or `--json` for a machine-readable report. It does
not prove model readiness, credentials, or provider permissions. Deployment
wrappers validate provider setup when executed. Server deployment runs on the
current machine or the configured Docker remote context.

Set `DOCUMENT_OCR_SKIP_PYTHON=1` when installing solely for remote clients or
hosting commands; `PASSPORT_OCR_SKIP_PYTHON=1` remains supported. Local OCR needs
the bundled Python runtime installed normally. Runtime dependencies are installed
against the included versioned dependency lock.


## Persistent background jobs

```typescript
const queued = await ocr.enqueueJob([frontImage, backImage], {
  documentType: 'us_driver_license', grouped: true, notify: false,
})
const progress = await ocr.job(queued.id)
if (progress.status === 'succeeded') console.log(progress.result)
await ocr.deleteJob(queued.id)
```

Jobs require an HTTP/local server with persistent job storage enabled; check
`catalog.capabilities.jobs`. Submitting a job does not retry automatically,
because a lost response could otherwise create duplicate persistent work.
Polling and deletion use normal transport retries. Job timestamps are Unix
seconds; results expire according to server retention. Notifications occur only
when `notify: true` and the server has an enabled notification integration.
