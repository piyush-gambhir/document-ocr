# Measured passport OCR improvements

For the latest results and the fixes to the remaining Greece and Latvia photo
failures, see the [passport recovery follow-up](MRZ_RECOVERY_FOLLOWUP.md).

Date: 2026-09-07. The unchanged 40-image public sample was run through the local
OCR pipeline before and after targeted MRZ changes. The original core was
exported from commit `e0765fd`; both runs used the same scoring code, corpus,
models and environment. The reports include actual core-source fingerprints
because the candidate was measured before its changes were committed.

| Passport measurement | Before | After |
| --- | ---: | ---: |
| Correct scored fields | 94/128 (73.44%) | 112/128 (87.50%) |
| Exact MRZ pairs | 10/16 (62.50%) | 13/16 (81.25%) |
| All eight scored fields correct | 10/16 | 14/16 |
| API success responses | 12/16 | 14/16 |
| Warm median latency | 593 ms | 720 ms |
| Warm p95 latency | 826 ms | 1,149 ms |

Four cases improve. No previously correct scored field or MRZ becomes incorrect,
and no previous success becomes a failure across the 40 auto-routed cases and
five additional US-hinted calls. The US and other document-family limitations
from the [baseline](PUBLIC_BASELINE.md) remain. This is four independent passport
identities, not a representative production or Indian passport accuracy estimate.
Latency figures are single-pass observations, not a stable performance guarantee.

## Changes

1. Given-name parsing stops at the observed padding terminator. OCR letters
   appearing later in padding no longer become extra name components. Single
   fillers still separate genuine name components, consistent with
   [ICAO Doc 9303-4](https://www.icao.int/publications/documents/9303_p4_cons_en.pdf).
   Raw MRZ text is retained and `MRZ_NAME_PADDING_NOISE` surfaces the anomaly.
2. A missing/damaged MRZ can trigger up to two focused OCR retries around a
   detected MRZ-like line. The text quadrilateral deskews the crop. Recovered
   boxes map back to the normalized page, keeping visual-field evidence usable.
   An observed complete name header ending in fillers may be padded to 44
   positions; incomplete names and identifiers are not synthesized.
3. Recovery accepts only checksum-valid TD3 pairs. Existing clean, valid MRZ
   pairs take no additional OCR pass. The same recovery runs on auto and hinted
   OCR paths; native PDF text and image-quality checks retain their behavior.

The Latvia template and Serbia photo now extract the right given names. The
Latvia upright scan and Azerbaijan photo now complete successfully. The latter
still has non-exact raw MRZ text, so it does not receive exact-MRZ credit. The
Greece and Latvia photos remain unsuccessful and need further investigation.

## Reproduce and compare

```bash
python -m benchmarks.public_accuracy --output benchmark-data/candidate.json
python -m benchmarks.compare_public_accuracy \
  benchmarks/reports/public-data/mrz-before.json \
  benchmark-data/candidate.json \
  --output benchmark-data/comparison.json
```

The comparator rejects changed scoring code, models, dependencies, hardware
metadata, corpus hashes, case IDs and field/MRZ denominators. It reports gains
and losses per opaque case/field; an improvement cannot hide another regression.
Its exit code is nonzero on scored regressions. Timing is reported, not gated.
The checked reports are [before](reports/public-data/mrz-before.json),
[after](reports/public-data/mrz-after.json) and
[comparison](reports/public-data/mrz-comparison.json). They contain no raw
identity fields or images. This is a smoke comparison, not the full release gate.

Validation: 609 unit/integration tests passed, 2 skipped; live before/after runs
completed without uncaught exceptions. Tests cover padding/noise, preserved name
components, valid-MRZ fast paths, checksum rejection, coordinate mapping,
degenerate geometry, bounded retries, and comparison consistency.
