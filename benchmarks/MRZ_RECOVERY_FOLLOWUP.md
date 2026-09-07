# Passport recovery follow-up

Date: 2026-09-07. This follows the [first MRZ improvements](MRZ_IMPROVEMENTS.md).
The same frozen 40-image smoke sample and five additional US-hinted calls were
run before and after the changes. The before core was exported from `d302446`;
reports fingerprint the actual core source, scorer, models and sample files.
No images were added or downloaded, and no labels or scoring rules changed.

| Passport measurement | Before | After |
| --- | ---: | ---: |
| Correct scored fields | 112/128 (87.50%) | 128/128 (100%) |
| All eight scored fields correct | 14/16 | 16/16 |
| Exact MRZ pairs | 13/16 | 15/16 |
| API success responses | 14/16 | 16/16 |
| Warm median latency | 722 ms | 825 ms |
| Warm p95 latency | 1,426 ms | 1,337 ms |

Two cases improve, with no scored field, exact-MRZ, success or runtime-error
regressions across all auto and hinted calls. These are single warm passes on a
shared machine; the median increased about 14%, and the lower observed p95 is
not evidence of a speed improvement. The fallback adds work only when recovery
is needed. This measures the local scan pipeline, not hosted HTTP performance.

## What was breaking

- **Greece photo: recovery clipped the text it needed.** The text detector found
  30 characters of the bottom MRZ line. Recovery used that partial bounding box
  as the width of its next crop, excluding the remaining characters. The crop
  now extends rightward using the observed character spacing and TD3's fixed
  44-character width. The existing 28-character minimum bounds that extension
  to about 1.57 times the detected width. OCR reads the added pixels; it does
  not fill in missing identifiers or check digits.
- **Latvia photo: detection missed the name line.** Even the deskewed band did
  not detect it. After band recovery fails, a complete bottom line can localize
  one name-line crop immediately above it. The existing Latin recognizer reads
  that crop directly. Admission requires at least 0.90 recognition confidence,
  a complete name header with an observed padding terminator, and a
  checksum-valid pair. Names themselves have no check digit; these guards are
  not proof that a name is correct. Only omitted trailing fillers may be padded.
- **Latvia photo: routing discarded the recovered MRZ.** The passport appeared
  above background writing, outside the bottom 40% of the detected page text.
  Page classification now accepts a checksum-valid MRZ elsewhere in the image.
  Its existing bottom-region heuristic remains available for damaged MRZs.

Recovery is bounded to two band OCR calls and at most one recognition-only
fallback per complete anchor. Successful band recovery skips that fallback;
existing clean, valid pairs skip recovery entirely. Direct recognition uses the
cached model's recognizer without changing its persistent detection settings.
Evidence coordinates map back to the original normalized page.

## Verification and remaining limits

622 Python tests passed, 2 skipped. New regressions cover clipped-crop pixel
coverage, direct recognition and coordinate mapping, checksum rejection,
uncertain or unterminated names, inference limits, cached-detector state, and
end-to-end routing with background text in both auto and passport-hinted modes.

The Azerbaijan photo still has an OCR error in trailing name-line padding.
Its eight scored fields are correct, but its raw MRZ is not exact and receives
no exact-pair credit. The earlier padding-noise warning is retained.

The 16 passport images represent only four identities and have now been used
to guide fixes. This is a tuning smoke suite, not an independent holdout or a
production accuracy estimate. **Indian passport accuracy remains unmeasured.**
US licence quality rejections and other document-family coverage gaps remain as
described in the [public baseline](PUBLIC_BASELINE.md) and
[dataset coverage map](DOCUMENT_DATASET_COVERAGE.md). Next evaluation work needs
new independently labelled identities and capture conditions, including Indian
passports, before stronger accuracy claims are justified.

## Reproduce

```bash
python -m benchmarks.public_accuracy --output benchmark-data/candidate.json
python -m benchmarks.compare_public_accuracy \
  benchmarks/reports/public-data/mrz2-before.json \
  benchmark-data/candidate.json \
  --output benchmark-data/comparison.json
```

Checked reports: [before](reports/public-data/mrz2-before.json),
[after](reports/public-data/mrz2-after.json), and
[comparison](reports/public-data/mrz2-comparison.json). They contain opaque case
IDs and scores, not images or extracted identity fields. The comparator refuses
mismatched corpus, scorer, model or environment provenance and exits nonzero on
scored regressions. Raw diagnostics stay in ignored `benchmark-data/`.
