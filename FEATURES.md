# Document OCR 3.1 implementation

This working tree adds country-aware extraction, eight experimental document
profiles, review tools and deployable worker kits. The original per-document
result blocks remain compatible. Read [HOSTING.md](HOSTING.md) for infrastructure
and the [SDK guide](packages/passport-ocr/README.md) for Node.js usage.

## Documents and evidence

| Profile | Implemented extraction | Coverage boundary |
|---|---|---|
| `us_driver_license`, `us_state_id` | AAMVA PDF417 directory/version parsing; barcode/printed-field reconciliation; US dates, state and address | Versions 01–11 are parsed; synthetic payload/image coverage does not establish accuracy across all states or historical layouts |
| `passport_card` | ICAO TD1 three-line MRZ with check digits and calendar validation | Supported travel-card prefixes only; not an arbitrary national-ID parser |
| `us_green_card`, `us_ead` | Supported TD1 card MRZs, USCIS/card numbers and labeled visual fields | Historical artwork/layout coverage remains unmeasured |
| `visa` | MRV-A and MRV-B parsing, component checks, labeled visual fields | MRZ expiry is not the holder's authorized period of stay |
| `us_i94` | I-94 number, holder, admission class/date and admit-until date or `D/S` | Conservative English labeled records; no CBP lookup |
| `us_w9` | Name, business name, EIN/SSN type and value, address | Labeled English forms; no signature, tax-status or IRS verification |
| Existing passport books | Existing TD3 path accepts US issuer codes and alphanumeric document numbers | The new US profile work does not certify every US passport generation |

`GET /documents` is the machine-readable capability catalog. It lists field
names, required fields, alternatives, extraction sources and experimental flags.
It also reports whether barcode decoding and persistent jobs are available.

Python and HTTP hints are `document_type` and `country`. SDK hints are
`documentType` and `country`. Country values normalize to ISO alpha-2; `USA` and
`IND` are accepted. `driving_licence` plus `US` selects `us_driver_license`.
Hints restrict routing and never turn an unidentified page into a valid record.

```python
from core.pipeline import scan

result = scan('card.png', document_type='us_state_id', country='US',
              include_evidence=True).to_dict()
print(result['documentFields'])
```

New profiles return `schemaVersion: 1`, `documentFields`, `issuingCountry`,
`issuingRegion` and `checks`. Legacy field blocks remain present. Legacy scans
also receive the new envelope when hints or evidence are requested. API field
and check names use camelCase; Python internals use snake_case.

`include_evidence=true` adds `fieldEvidence` and `imageSize: [width, height]`.
Each evidence item contains the observed text, a four-point bounding polygon,
source (`ocr`, `pdf_text`, `mrz`, `pdf417`), and extraction confidence. These are
heuristics/source scores, not calibrated probabilities of correctness or identity.
Evidence is supplied only when a source match exists. An MRZ/barcode region may
support several fields. Conflicting barcode/printed values prevent success.
Checksums and PDF417 structure do not authenticate an issuer; new profiles expose
`issuerAuthenticated: false`.

## PDFs, batches and grouped pages

Digital PDFs use their native text layer first, falling back to OCR for an
unidentified page. The response warns `PDF_NATIVE_TEXT_NOT_VISUALLY_VERIFIED`:
hidden text can disagree with the rendered document. Review the rendered source
when the distinction matters. PDF coordinate conversion uses PDFium's own
transform, including CropBox offsets. Rotated PDF pages use rendered OCR.

- `POST /scan`: one multipart `image`; a multi-page PDF scans its first page and
  reports `PDF_ADDITIONAL_PAGES_IGNORED`.
- `POST /scan/batch`: repeated multipart `images`; independent inputs, in order.
  Each PDF has the same first-page behavior as `/scan`.
- `POST /scan/document`: repeated `images` belonging to one document/holder;
  expands PDFs into pages and reconciles their fields. Returns `results`, merged
  `documentFields`, `conflicts` and `errors`. Different document families or
  conflicting values fail reconciliation; conflicting fields are not silently
  selected. Pages without a shared identifier still depend on the caller's
  association. This is not a general packet-splitting or household-table merger.

Synchronous requests have a 10 MiB combined upload cap, at most ten input/pages,
and a 60-second queue-plus-execution deadline. A timed-out native operation keeps
its concurrency slot until it exits. Use jobs for longer persistent-server work.
Rendered PDFs are bounded to 20 million pixels/page and 40 million/document;
input images are bounded to 40 million pixels. Encrypted PDFs are rejected.

Single scans return 422 for extraction failure, with the complete result.
Batch/group responses return 200 with `success`, `partial` or `failure` in their
body; HTTP errors represent a failed request rather than an incomplete record.

## Review and redaction

Open `/review` on a reachable server. Enter its API token if configured, choose a
file and extract. The screen displays original source text/regions, editable
values and the original JSON. Exported JSON preserves the original extraction
and a separate correction list; CSV includes original and corrected values and
escapes spreadsheet formulas. The token and corrections remain in tab memory.

`POST /preview` returns the normalized first-page PNG used by evidence geometry.
`POST /redact` takes `image` and a JSON `boxes` form field containing selected
four-point polygons **in that normalized coordinate plane**, not the original
camera image. It burns black rectangles into a metadata-free PNG. It removes the
original PDF text layer by rasterizing; it does not automatically find every
sensitive value, photograph, background identifier or later PDF page. Review the
exported PNG before sharing. The original input is not modified.

The static `/review` page is public so a browser can reach its token-entry form;
all document, preview, redaction and job routes enforce `API_TOKEN` when set.
Platform IAM may impose an additional authentication layer. Responses are marked
`Cache-Control: no-store`. Synchronous inputs/results are not persisted by the
application; the browser owns its selected file and exports.

## Optional persistent jobs

Jobs require a persistent local server volume and a **separate worker process**.
They remain unavailable on the default Cloud Run, Lambda and Cloudflare presets.
See the opt-in Compose jobs profile in [HOSTING.md](HOSTING.md). Do not put this
SQLite queue on an ephemeral disk or network filesystem.

```bash
export DOCUMENT_OCR_JOBS_DIR=/var/lib/document-ocr
# Generate once, securely store it, and give the same key to API and workers.
export DOCUMENT_OCR_JOB_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export DOCUMENT_OCR_JOB_RETENTION_SECONDS=86400
python -m core.jobs worker
```

Keep the key across restarts; replacing it cannot decrypt existing work. A stored
encrypted key sentinel rejects a mismatched key before any job is claimed. Key
rotation/migration is not implemented. Retention may be configured from 60 seconds
to seven days; the default is one day. The worker removes expired rows, and the
API never returns expired records. Deletion/expiry cannot stop native code that
is already running, but its eventual result cannot recreate the deleted job.

`POST /jobs` accepts repeated `images`, scan options, `grouped` and `notify` form
fields, and returns 202. `GET /jobs/{id}` polls; `DELETE /jobs/{id}` deletes queued
inputs/results. The queue holds at most 1,000 retained jobs. Inputs and results
are encrypted with Fernet; input ciphertext is cleared on completion. Metadata
such as job ID, status and timestamps remains visible in the database. All users
of the same configured API token share one queue: this is a single-tenant server.

Statuses are `queued`, `running`, `succeeded`, `failed`. `succeeded` means the job
executed; inspect its nested scan result for extraction success. A crashed worker's
lease is reclaimable after one hour, up to three attempts. Ordinary processing
errors fail the job; they are not retried indefinitely. Notifications use
at-least-once delivery with a stable event ID and up to six attempts, five minutes
apart, within retention.

Webhooks go only to the operator-configured `DOCUMENT_OCR_WEBHOOK_URL` (HTTPS),
with a `DOCUMENT_OCR_WEBHOOK_SECRET` of at least 32 characters. Clients cannot
supply callback URLs. Request `notify=true` when enqueuing. The body contains only
`id` and `status`; fetch the result through the authenticated API. Verify
`X-Document-OCR-Signature: sha256=<HMAC>` over the exact bytes
`<X-Document-OCR-Timestamp>.<body>`, enforce timestamp freshness, and deduplicate
`X-Document-OCR-Event`. Redirects are disabled. Set both webhook variables on the
API and worker so submission and delivery share configuration.

## Deployment and next work

The kits include Cloud Run, Lambda with inline/S3 input, Cloudflare Worker plus
native Container, and Compose/Caddy server hosting, with Terraform roots for
Cloud Run and Lambda. The npm CLI scaffolds source and pinned dependencies,
checks prerequisites, and dispatches a selected target; it does not publish or
create cloud resources during `init` or `deploy --dry-run`.

Not implemented by this change: bank-statement transaction tables, utility-bill
and payslip schemas, GST/Udyam/incorporation/cheque profiles, automatic packet
splitting, text-line deskew/orientation search, issuer verification, multi-tenant
queues, and cloud-native distributed job backends. Aadhaar Secure QR signature
verification also remains deferred: it needs the correct current QR trust chain,
a verified format specification and signed fixtures; the paperless offline e-KYC
certificate must not be assumed to verify Secure QR data. [UIDAI's certificate
catalog](https://uidai.gov.in/en/data-and-download) lists these as separate
certificate families.

The new [structured-document benchmark](benchmarks/STRUCTURED_DATASET.md) enforces
independent groups, negative controls and exact identifier/date gates for all eight
new profiles; its empty example deliberately cannot pass.

The next accuracy gate is a consented image corpus with separate tuning/locked
splits, holder/state/layout/language slices, negative controls, and per-field
identifier/date exact match. Synthetic parser/transport tests and a clean build
are useful regression checks, not a production accuracy percentage.
