# Private passport accuracy dataset

Run `make benchmark` with an ignored `benchmark-data/manifest.json`, or set
`DOCUMENT_OCR_BENCHMARK_DATA` to a private dataset directory. The manifest maps
opaque, relative asset filenames to expected serialized scan results. All assets
must exist inside that directory before OCR starts.

Each sample must annotate `status` and `pageType`. `documentType` defaults to
`passport`; annotate it explicitly for unrelated negative controls. Use `fields`
for biodata extraction and `backPageFields` for back-page extraction. Annotate
`mrzRaw` as two strings, and include `mrzValid` and `unsupportedReason` where
these outcomes matter. Additional annotated metadata participates in the
status/metadata accuracy gate.

The benchmark emits an aggregate JSON report without filenames, identity fields,
OCR warnings, or exception messages. It exits `0` when all release gates pass,
`1` when a measured gate fails, and `2` for dataset or warmup/setup failures.

A passing release report requires measured field accuracy, MRZ exact matches,
non-biodata outcomes, and biodata latency. Missing denominators appear as `null`
and fail their gates. Every expected-success biodata sample must have a valid
positive latency, and any scanner exception fails the run. One biodata image
warms the scanner before the measured pass. Both `fields` and `backPageFields`
contribute to field accuracy; routing/metadata errors receive no field or MRZ
credit. Field scoring evaluates each annotated key, so annotate all fields that
matter, including explicitly absent values as `null`.

The built-in thresholds are 95% status/metadata accuracy, 97% field accuracy,
99% MRZ exact match, 95% non-biodata accuracy, and at most 5000 ms median warm
biodata latency. These are release gates, not evidence of achieved accuracy.

Keep real documents and annotations private. Use holder-disjoint tuning and
locked-test splits, representative captures and variants, and negative controls.
The synthetic evaluator tests verify scoring behavior only; they do not measure
OCR accuracy on document images. For detailed collection and annotation practices,
see [the KYC dataset guide](KYC_DATASET.md).
