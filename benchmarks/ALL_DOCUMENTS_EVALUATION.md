# Dataset-sourced OCR accuracy and latency

Updated 2026-09-08. **Accuracy evaluation now uses downloaded dataset documents
only.** Locally generated images and the agent-transcribed EAD specimen are
excluded from the active evaluation and CI. Existing generated fixtures remain
available as engineering contracts, but their scores are not accuracy evidence.
The attempted generated timing confirmation was stopped when this policy changed.

## Dataset scope

The fixed sample contains **62 images in 33 source-document groups**:

- 39 labelled positive views: 24 non-Indian passport book views, four US
  passport-card fronts, five South Dakota licences and six W-9 forms.
- Seven unrelated-document negative controls.
- 16 observations without usable field truth, including four Aadhaar images.
  These do not contribute to field accuracy.

Images and labels come from MIDV-2020, MIDV-500, MIDV-LAIT, IDNet, CORD-v2 and
Symage, through the [original](public_samples.json) and
[expansion](public_expansion_samples.json) manifests. No full dataset is fetched.
Source links, annotation mappings, checksums and sample selection remain in the
[dataset catalog](PUBLIC_DATASETS.md) and [coverage map](DOCUMENT_DATASET_COVERAGE.md).

Dataset-sourced does not necessarily mean an issued personal document: IDNet and
Symage supply synthetic documents, and the MIDV identity datasets include
fictional/specimen records. These are externally supplied images and labels,
not images produced by this project. Multiple captures, format conversions and
repetitions do not create independent holders. This corpus has guided fixes;
it is a tuning suite, not an untouched release holdout.

**Only four of the 15 supported profiles have labelled positive dataset coverage.**
Real Indian passport accuracy and the other missing profiles remain unmeasured.
Aadhaar observations cannot substitute for valid, independently labelled positive
samples. The coverage map records gaps rather than filling them with generated
accuracy claims. The previously inspected EAD has a known name conflict; its
agent transcription is retained as research material, outside these results.

## Paired core results

Starting revision: `00f44263186260ac9b9cb3fa2ece01fc50ee3b86`.
Final OCR implementation: `d165c214016e56a79aaf9e8c73ae9471c6a1501d`.
The candidate's core source SHA-256 is
`8f02315361741b2595d3f0faa37f93e55d5161223d9400458d11281ebd98495b`.

Both revisions used the same images, labels, evaluator and model files, with
three repeats per image: **372 measured core calls**. Runs used an Apple M5 Pro,
macOS 26.6.2 arm64, Python 3.12.13, RapidOCR 3.9.2 and ONNX Runtime 1.28.0;
Python reported 15 CPUs. `DOCUMENT_OCR_KYC_LANGS` was unset. Timing is local and
warm; it does not predict a different CPU, additional languages, network transit
or serverless cold starts.

| Metric | Before | After |
|---|---:|---:|
| Exact fields per pass | 250/266 (93.98%) | 260/266 (97.74%) |
| Complete positive records per pass | 36/39 | 38/39 |
| Raw passport MRZ pairs per pass | 21/24 | 22/24 |
| Rejected negative images per pass | 7/7 | 7/7 |
| Whole-workload warm p95 | 2,081 ms | 1,980 ms |

Every repeat agreed. There were no runtime errors, unstable outputs or spurious
optional fields. Whole-workload timing includes negative controls and unscored
observations. Field denominators count unique views, not repeated calls.

| Profile | Views | Exact fields before → after | Complete after | Candidate warm p95 |
|---|---:|---:|---:|---:|
| Passport books | 24 | 184/192 → 192/192 | 24/24 | 1,196 ms |
| US passport-card fronts | 4 | 16/24 → 18/24 | 3/4 | 665 ms |
| South Dakota licences | 5 | 20/20 → 20/20 | 5/5 | 236 ms |
| W-9 forms | 6 | 30/30 → 30/30 | 6/6 | 2,184 ms |

On matched successful workloads, passport median latency improved 774 → 583 ms,
and US licence median improved 425 → 225 ms. W-9 median was 1,929 → 1,953 ms;
not every timing metric improved. All fixed relative accuracy and matched-workload
latency gates pass without changing their 20%/100 ms allowance.

Absolute targets remain unmet: one blurred handheld passport-card image is
rejected, and negative-control p95 is **3,155 ms**, above the 2,500 ms target.
The rejected positive remains in the denominator. All 24 passport views have
correct scored fields, but two raw MRZ pairs retain filler/subtype differences.
Field accuracy and exact raw-MRZ accuracy remain separate.

## Real HTTP evaluation

The same downloaded images are submitted to the production FastAPI application
in a separate authenticated uvicorn process. Client concurrency is one, two
and four. A worker admits one OCR operation at a time, so concurrent clients
measure queuing rather than parallel inference. Throughput is closed-loop and
local, not a production SLA or an autoscaling capacity claim.

For each of the four labelled profiles, the manifest's first sample is also
submitted as PNG, JPEG and raster PDF, with a hint, and with evidence enabled.
Selection is independent of OCR success. These are 20 extra format/options
checks per revision, not new documents. The HTTP runner additionally exercises
authentication, invalid uploads/hints, batch ordering, grouped duplicate pages
and actual encrypted queued-job processing, polling and deletion.

The final paired HTTP run has **372 measured scan requests**, in addition to
40 format/options checks across the two revisions. Together with core evaluation,
that is **744 calls in the final paired comparisons**, not 744 unique documents.
All concurrency levels retain 260/266 exact fields per pass. The 20 format/options
checks improve from **106/115 to 115/115 exact fields**. All ten API/job checks
pass, with no transport/runtime errors, response instability or accuracy
regressions. Operational HTTP checks pass.

**The local relative HTTP timing gate fails.** A fresh sequential baseline and
candidate pair reproduced timing failures after the first comparison against
the earlier baseline also failed. The final pair reports 17 per-profile timing
gate failures across the three concurrency levels. No thresholds were relaxed,
and neither failed comparison is discarded.

| Clients | Whole-workload p95 before → after | Requests/s before → after |
|---|---:|---:|
| 1 | 1,827 → 2,444 ms | 1.369 → 1.080 |
| 2 | 3,681 → 4,286 ms | 1.309 → 1.072 |
| 4 | 5,547 → 7,763 ms | 1.267 → 0.997 |

These results do **not** establish lower HTTP latency or improved throughput.
The passing core comparison cannot override a failing HTTP comparison. A
controlled benchmark on the intended worker hardware remains necessary before
claiming a latency improvement under load.

An eight-case profile-balanced dataset probe with `DOCUMENT_OCR_KYC_LANGS=en`
matched default score/status outcomes exactly. This is score parity for those
cases, not timing equivalence or full-corpus language coverage.

### Performance diagnostics

Profiling the first dataset passport and W-9 found most time in ONNX inference.
The candidate used fewer native inference calls for the passport and the same
count for W-9; this observation does not invalidate the HTTP timing failures.
Three dataset images were then used for bounded runtime-configuration probes:
one, two and four inference threads were all slower than automatic threading.
Enabling the ONNX memory arena gave no useful speed gain and increased peak
process memory. Neither runtime setting was changed in production. These small
probes are diagnostics, not additional population-accuracy evidence.

## What was breaking

- Full-page reads were repeated on cards and sparse pages. Routing now reuses
  the first read and uses bounded recovery only when evidence is incomplete.
- Merged labels and values lost fields; name extraction could prefer a parent's
  name. Label parsing preserves inline values and field-specific name priority.
- Valid partial passport MRZ anchors were discarded. Bounded pixel rereads now
  require checked identifiers/dates and preserve existing correct fields.
  Unknown country codes fail validation; special codes follow
  [ICAO Doc 9303 Part 3](https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf).
- Raster PDFs skipped contrast processing. Enhancement now changes colors only,
  preserving renderer dimensions, previews and evidence coordinates. Recognized
  native-text PDFs still avoid both OCR and enhancement.
- Joined `USASD`/`ExpiresOn` tokens and small overlapping or differently angled
  text boxes lost licence/card fields. Bounded geometry rules retain barriers
  that prevent borrowing a neighbouring field's value.
- Truncated card expiry dates need fresh pixels. A sole missing expiry permits
  up to two direct reads of its observed box, then an existing cluster read if
  still incomplete. New dates need at least 0.9 confidence, must preserve the
  observed prefix and cannot change existing fields. Complete cards incur no
  recovery reads.

No production recovery uses fixture IDs, expected answers or publisher crop
coordinates. The blur threshold is unchanged. See the
[recovery notes](REMAINING_RECOVERY_NOTES.md) for guards and remaining failures.

## Verification and reproduction

The implementation passes **817 Python tests**, **82 SDK tests**, SDK typecheck
and package build. Two optional private-dataset tests are skipped because no
private manifest is configured. Unit tests establish code behavior; the dataset
runs above establish measured image accuracy. PDF tests include actual-ink
redaction and native/raster paths in both single and grouped APIs.

```bash
.venv/bin/python -m benchmarks.public_data fetch-samples
.venv/bin/python -m benchmarks.public_data fetch-samples --manifest benchmarks/public_expansion_samples.json
.venv/bin/python -m benchmarks.multidoc_accuracy --output benchmark-data/public/current.json
.venv/bin/python -m benchmarks.http_accuracy --output benchmark-data/http/current.json
```

For a paired comparison, export the baseline revision's `core` and `deploy`
directories with `git archive`. Put that export first on `sys.path` for baseline
core evaluation, and pass it as HTTP `--source`. Run the candidate with
`--baseline before.json`; core additionally uses `--regressions-only`.
The same current evaluator must score both revisions. Run timed jobs sequentially
on the same otherwise quiet machine, keeping source, inputs and policy fixed.

[Core CI](../.github/workflows/ocr-evaluation.yml) and
[public HTTP CI](../.github/workflows/ocr-http-public.yml) now use only downloaded
public datasets. Core gates repeated field/status/negative/stability and matched
latency regressions. HTTP additionally gates API consistency and lost fields
across input formats. Absolute failures stay visible even when a relative gate
passes. Generated fixtures and the agent-transcribed EAD are not run by these
workflows. Sample downloads in core CI have three bounded attempts and still
require the pinned bytes; OCR failures are never automatically retried away.

The [dataset-only public HTTP workflow](https://github.com/piyush-gambhir/document-ocr/actions/runs/34205636555)
passed on the hosted runner. Its baseline and candidate contain the same final
OCR source, so it verifies the new gate, not an accuracy or speed uplift over the
original revision. [Implementation unit/build CI](https://github.com/piyush-gambhir/document-ocr/actions/runs/34169486975)
also passed. The [latest dataset-core CI run](https://github.com/piyush-gambhir/document-ocr/actions/runs/34206534687)
failed before OCR because sample downloads returned HTTP 504 on all three
attempts; the preceding attempt encountered HTTP 502. Local repeated core
results above are available, but that latest hosted core run is not a test pass.

[Paired score-only reports](reports/all-documents/) retain per-case scores,
latency and model/environment fingerprints. Images and raw responses remain
under ignored `benchmark-data/`. No package publication or live deployment was
performed.
