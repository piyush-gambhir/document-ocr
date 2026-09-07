# Repeated multi-document evaluation

Date: 2026-09-08. This expands the original 40-image smoke suite with 22 images
selected before OCR measurement. The suite now has **62 images and 33 independent
source-document groups**. The new cases represent four new passport identities,
one US passport-card specimen in four views, six synthetic W-9 identities, and
four unrelated forms. This is evaluation, not training.

## Measured results

Both revisions completed 186 measured calls: 62 images × three repetitions,
for **372 measured calls** in the comparison. All per-case results were stable.
The table below shows exact field accuracy and complete records per unique image;
repeating a case does not add an independent example.

| Profile | Images | Fields before → after | Complete records after | Warm p95 before → after |
| --- | ---: | ---: | ---: | ---: |
| Passport book | 24 | 83.33% → **95.83%** | 23/24 | 1100 → 996 ms |
| US licence (South Dakota) | 5 | 0.00% → **100.00%** | 5/5 | 4 → 393 ms |
| W-9 | 6 | 0.00% → **100.00%** | 6/6 | 3016 → 1862 ms |
| US passport-card front | 4 | 8.33% → **66.67%** | 2/4 | 608 → 519 ms |

The four scored profiles improve from 162/266 to **250/266 exact fields
(93.98%)** per stable repetition. All seven unrelated controls were rejected
in every repeat (21/21), with no invented W-9 business names, exceptions or
scored regressions. Exact passport MRZ pairs improve from 18/24 to 21/24.

The regression check passes, but the absolute target check **does not pass**:

- Passport-card fronts: 16/24 fields and 2/4 complete captures. The hand capture
  is rejected as blurry; the clutter capture misses its number and expiry date.
  Those failures stay in the denominator. This remains one underlying specimen.
- The Azerbaijan identity-41 photo still loses its MRZ; the other 23 passport
  cases complete.
- Unrelated-form controls have a 2,778 ms warm p95, above the 2,500 ms target.
  Their median is 887 ms. Expensive rejection remains a performance gap.

Observed median/p95 for the unscored Aadhaar subset is 173/358 ms. The other
observation subset is 452/1,011 ms; its median increased from 237 ms as compact
images previously rejected before OCR now receive a read. No field-accuracy
claim is made for these subsets. US licence latency likewise rises from a
pre-OCR rejection (2 ms median) to actual extraction (383 ms median).

For the same 60 successful passport calls in both revisions, median latency
improves from 744 to 573 ms and p95 from 1,100 to 903 ms. W-9 median improves
from 2,850 to 1,768 ms. Cold first-call time was 946/981 ms before/after. These
are observations on this machine, not portable timing guarantees.

Validation: **655 Python tests passed, 2 skipped**. Workflow YAML and embedded
shell syntax were checked locally. Hosted CI results are separate from these
local measurements. Checked score-only reports:
[before](reports/multidoc/before.json) and [after](reports/multidoc/after.json).

## Sample and provenance

The original [manifest](public_samples.json) remains unchanged. The separate
[expansion manifest](public_expansion_samples.json) pins every added image and
annotation by hash, byte size and exact archive member or viewer row. It adds
about 51 MiB of unique local data. Each manifest retains the 100 MiB payload and
transfer ceiling; full archives and parquet shards are never downloaded.

| Source | Added cases | Selection and limits |
| --- | ---: | --- |
| [MIDV-2020](https://zenodo.org/records/18786808) | 8 | Identity 41, the next archive member after 00, for Azerbaijan/Greece/Latvia/Serbia; rotated scan and photo. Eight total passport identities including the original sample. CC-BY-SA-2.5. |
| [MIDV-500](https://zenodo.org/records/18504926) | 4 | US passport-card template and first table/iPhone, hand/Samsung and clutter/Samsung frames. Text labels come from the publisher's template; capture frames share that specimen's truth. One identity, not four independent examples. CC-BY-SA-2.5; retain publisher/source notices. |
| [Symage synthetic US forms preview](https://huggingface.co/datasets/Symage/synthetic-us-forms-preview) | 10 | Test rows 60–65: six W-9s. Rows 30/50/70/85: 1040, CMS-1500, I-9 and invoice controls. Renderer-produced FUNSD key/value links, not OCR-generated labels. CC-BY-4.0; credit Symage, Inc. / [SymageDocs](https://symagedocs.ai). |

The selected W-9s all use SSNs; this does not measure EIN or handwriting accuracy.
The passport card is a front-side specimen, not a TD1/back-side benchmark. Source
images and extracted fields remain in ignored `benchmark-data/`. Checked reports
contain only opaque IDs, counts, match booleans and timings.

## Scoring and timing

`multidoc_accuracy.py` runs the real local `core.pipeline.scan` API. It warms each
family, shuffles all cases with a fixed seed, and runs three complete repetitions.
Before and after use the same scorer, policy, corpus, models and Python packages.
The baseline core is exported from `d3d1a27`. Actual core source fingerprints record
the measured code even when implementation changes have not yet been committed.

- Passport books: eight exact MRZ-derived fields and exact raw MRZ pairs. Dates
  score YYMMDD, not inferred century. Passport cards: six independently mapped
  publisher fields. US licences: four publisher identifier/date fields.
- W-9: five nonempty exact fields; the blank business-name field is checked
  separately for invented values and does not inflate positive field accuracy.
- All failed/rejected positives stay in field denominators. Complete-record
  accuracy and API acceptance are separate; extracting correct fields inside a
  failed response does not earn acceptance credit.
- The seven unrelated controls include the original three receipts. False
  acceptance is gated. Crashes are never counted as correct rejections.
- The four Aadhaar and twelve other observation cases have **no verified field
  accuracy denominator**. Their failures, timing and stability remain visible.
- Repeated calls do not increase independent image/identity counts. Each case's
  field matches, routing and status must be stable across repeats.
- Warm median and p95 are reported separately for each family, with additional
  successful-call timing. Cold startup is separate. HTTP, deployment, network
  upload and concurrent-worker capacity are not measured by this local test.

## Regression checks

The checked [policy](multidoc_policy.json) sets initial goals of 95% exact field
accuracy, 90% complete records/acceptance, and 2,500 ms warm p95 per family. These
are engineering targets, not production SLAs or statistical guarantees. Missing
family coverage, exceptions, unstable results, invented optional values and false
acceptances are explicit failures.

A comparison also rejects changed corpus/scorer/model/environment fingerprints,
changed IDs or field denominators, and any previously correct field, raw MRZ,
route, absence or successful status becoming incorrect. Relative latency checks
compare the same successful workload, with a 20% or 100 ms noise allowance,
whichever is larger. Newly readable cards are not compared against their former
millisecond pre-OCR rejection path. At least five comparable calls are required.

`--regressions-only` requires a matched baseline and keeps absolute target failures
visible while gating regressions and operational errors. Passing that check does
**not** mean all document families meet the absolute accuracy target.

## Run locally

```bash
python -m benchmarks.public_data fetch-samples
python -m benchmarks.public_data fetch-samples --manifest benchmarks/public_expansion_samples.json
python -m benchmarks.multidoc_accuracy --output benchmark-data/multidoc/current.json
python -m benchmarks.multidoc_accuracy \
  --baseline benchmark-data/multidoc/current.json \
  --output benchmark-data/multidoc/candidate.json
```

`make benchmark-public` runs the same evaluator. `OCR_BASELINE` and `OCR_REPORT`
select comparison/report paths. The default CLI fails when any absolute target
is unmet. Use one repeat only for diagnostics; it cannot satisfy the three-repeat
gate. Keep baseline and candidate runs sequential on an otherwise quiet machine.

The [OCR regression workflow](../.github/workflows/ocr-evaluation.yml) runs on PRs and main-branch pushes
affecting OCR, benchmarks or dependencies and can be dispatched manually. It
exports the base core and measures both revisions with the candidate evaluator
on the same runner. It gates regressions and shows unmet absolute targets in the
job summary. It never uploads images or raw extraction output.

## Implementation changes

- Portrait inputs reuse full-page OCR and retain a targeted fallback when MRZ
  evidence is weak, avoiding duplicate reads for recognized forms/passports.
- Sideways text can trigger at most two quarter-turn reads. MRZ pairing uses
  local line axes for mapped-back vertical evidence. A small passport with no
  detected MRZ can trigger one focused reread around confident document text.
- W-9 identification tolerates heading fragments interleaved with neighbouring
  columns. Boxed TINs use a bounded direct-recognition crop. An uncertain read
  requires the same nine digits after removing ruling lines and rereading.
  This is agreement between two views of the same model, not independent proof.
- Field matching follows a label's angle. Large specimen watermarks and nearby
  dates cannot become personal names; W-9 section boundaries prevent borrowing
  instructions into blank fields. Card date/number and US printed field labels
  handle observed spacing and numbering variants.
- Compact images are admitted at a minimum 450-pixel short side and 750-pixel
  long side, alongside the existing general 600-pixel rule. Blur and field
  completeness checks still apply; admitted compact images carry a warning.

## Remaining coverage limits

This sample has been used to guide fixes and is now a tuning suite, not an
independent release holdout. Indian passport accuracy remains unmeasured, US
licence positives cover only South Dakota, and the single passport-card identity
cannot support a general accuracy claim. The linked [coverage catalog](DOCUMENT_DATASET_COVERAGE.md)
records the gaps for all 15 supported profiles. More independently labelled
identities and capture conditions are needed before a release-wide claim.
