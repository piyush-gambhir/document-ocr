# Real HTTP OCR evaluation

`http_accuracy.py` starts the production FastAPI application in a separate,
authenticated uvicorn process bound to loopback. It submits the small local,
checksum-pinned corpus as real multipart HTTP requests. It does not call the
pipeline directly or replace OCR with mocked responses.

```sh
.venv/bin/python -m benchmarks.http_accuracy \
  --output benchmark-data/http/current.json
```

The default sweep sends each public image once at each client concurrency of
1, 2, and 4. Repetition measures stability and timing; it does not add independent
documents. `--repeats 3` repeats each sweep. A maximum of 1,000 measured `/scan`
requests keeps this a bounded smoke evaluation. The report records document
count and identity-group count separately from requests.

Use `--manifest` repeatedly to select another admitted corpus with publisher-linked
images and annotations. `--root` sets its local sample directory.
`--case-limit` selects a deterministic, profile-balanced subset and refuses a
limit too small to cover every included profile. Corpus selection is independent
of OCR outcomes. No downloads happen during this evaluator.

```sh
.venv/bin/python -m benchmarks.http_accuracy \
  --concurrency 1 2 4 --repeats 1 \
  --output benchmark-data/http/public.json
```

The report separates:

- Process launch to `/ready`, including model initialization, from the first
  scan and subsequent requests.
- Client latency, measured from request submission through response receipt,
  from the server's own `processingMs`.
- Completed requests per second from latency at each client concurrency.
- Time outside reported OCR processing, which includes upload, queue wait,
  HTTP handling, serialization and timer differences. It is **not** a direct
  measurement of queue wait.
- Field accuracy and complete-record accuracy from transport reliability and
  consistency. Stable incorrect fields remain incorrect.

The server admits one OCR operation at a time per process. Concurrent clients
therefore measure queuing at that worker, not parallel OCR speed. The sweep is
closed-loop: a client starts another request after its previous response. It
does not establish an open-loop overload limit, internet latency, memory
capacity, cold serverless startup, autoscaling behavior, or a production SLA.
Run comparisons alone on the same hardware and pinned model versions.
The paired local reports use the default configuration with
`DOCUMENT_OCR_KYC_LANGS` unset; the exact value is recorded in provenance.
Deployments explicitly setting it to `en` need a separate equivalence check,
and adding other OCR languages requires another matched timing/accuracy run.
Changing language configuration is not an interchangeable baseline.

After the timed sweep, bounded route checks verify authentication, capability
discovery, rejection of invalid uploads and hints, batch ordering, agreement of
grouped duplicate pages, and an actual asynchronous job. Jobs use a temporary,
encrypted local queue and a separate OCR worker; the check submits, polls,
compares the result with `/scan`, and deletes the job. It never sends webhooks.
These extra checks and the first scan are excluded from throughput statistics.

For each registered document profile present in the corpus, additional checks
submit a PNG, a high quality JPEG, an image-only PDF, a scan with an explicit
document hint, and a scan requesting evidence. The active dataset evaluation uses the manifest's first case for that profile;
it never chooses a case because OCR succeeded. Encodings are created in memory
from the original image. The PDF has no native text layer that could substitute
for image recognition. Each result is scored against the same independent truth
and compared with the automatic original scan. Lost previously correct fields
or success statuses are reported and fail the operational check. These are
additional API paths and encodings of existing cases, not new independent
documents. Their measurements remain separate from the concurrency sweep.

Every valid response at concurrency 2 or 4 is compared with the complete
sequential response, ignoring only `processingMs`. HTTP errors, timeouts,
invalid response schemas, or changed extraction results fail the operational
gate. HTTP 422 for an OCR quality rejection is a valid API response, but a
rejected positive document still loses its expected field-accuracy credit.
Missing absolute accuracy or latency targets must be assessed separately from
the operational gate.

`--source /path/to/exported/revision` runs another revision's server and core
with the current evaluator and corpus. Reports fingerprint that source and the
manifests. Compare a new run with `--baseline benchmark-data/http/before.json`.
The evaluator, scorers, corpus, model weights, packages, platform, client/server
configuration, random seed, and repetitions must match. The comparison rejects
any previously correct field, absent-field check, MRZ, route, negative rejection,
or successful status becoming incorrect. It also compares median and p95 HTTP
latency within each document profile and client concurrency, using calls with
matching status and document type. At least five matching calls are required;
fewer calls are explicitly reported as unmeasured. An increase exceeding the
larger of 20% or 100 ms fails the relative latency gate. This allowance is fixed,
not adjusted to excuse a measured slowdown. Throughput changes are report-only.

These relative checks do not establish absolute accuracy or latency targets.
The document-corpus evaluator reports those targets separately; an operational
HTTP pass never makes a missed corpus target pass. Never compare unrelated
datasets or competing workloads as evidence of an improvement.
`--startup-timeout` and `--request-timeout` bound startup and
individual requests. Model initialization failures stop before repeated scans.

Reports contain case identifiers, scores, counts, consistency failures, and
timing; expected values, OCR fields, uploaded bytes, bearer tokens and job keys
are not serialized. Server diagnostics remain in the ignored
`benchmark-data/http/server.log`. The focused unit tests exercise evaluator
error accounting; only running the CLI produces real OCR HTTP measurements.

Active CI and accuracy reporting use downloaded dataset images only. The runner's
generic manifest support is not evidence for an unmeasured profile. Locally
generated fixtures and the agent-transcribed EAD specimen are excluded from
automatic accuracy evaluation. See [current results](ALL_DOCUMENTS_EVALUATION.md).
