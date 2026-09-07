# Public OCR evaluation data

Research date: 2026-09-07. This phase links sources and prepares a small evaluation sample. The [first OCR baseline](PUBLIC_BASELINE.md) reports measured results on this sample;
an automatic regression gate is not enabled yet.

The machine-readable [catalog](public_datasets.json) pins 145 publisher files,
totaling **447.58 GiB** before extraction. It contains the full published image
releases for the four MIDV collections below, all eight IDNet parts (20 layouts),
and all six CORD v2 shards. Additional candidates have explicit access/terms or
coverage-gap statuses. This is a relevant collection, not a claim to enumerate
every OCR dataset in existence.

## Fixed evaluation sample

We are evaluating OCR, **not training a model**. Keep the catalog as links; do not
mirror the datasets. The frozen [sample manifest](public_samples.json) contains
**40 images across 18 identity groups**, plus publisher annotations, totaling
**57.25 MiB**. Images and labels stay outside Git. This is a smoke benchmark,
not a representative population estimate or complete document-profile coverage.

| Source | Images | Independent groups | Purpose |
| --- | ---: | ---: | --- |
| MIDV-2020 | 24 | 6 | Four TD3 passport layouts and two generic ID layouts; each template, upright scan, rotated scan and photo shares one identity. |
| MIDV-LAIT | 8 | 4 | Gujarati, Malayalam, Thai and Arabic-script documents; paired templates/frames. |
| IDNet South Dakota | 5 | 5 | Synthetic US licence fields. Other US jurisdictions remain link-only. |
| CORD v2 test | 3 | 3 | Receipt semantic regions and field extraction. |

Selection uses the first source identity/row within the listed categories and
is frozen before running our OCR. It is intentionally small and not random.
Repeated views are not independent examples. No training split is downloaded.
The manifest records selection rules, identity groups, source archive checksums,
exact byte ranges and per-file SHA-256 hashes. The selected MIDV template JSONs
contain annotations for other identities too; only the selected filename is
used. No full image archive or Parquet shard is required.

The bulk archives from the initial research pass have been removed after
preserving this sample. Historical aggregate audits below remain as research
notes; they do not describe data retained locally.

## Sources and relevance

| Dataset | Pinned size | Labels and use | Access / rights |
| --- | ---: | --- | --- |
| [MIDV-2020](https://zenodo.org/records/18786808) | 16.24 GiB | 1,000 mock documents; template text plus scans, photos and capture frames. Four international passport layouts match current TD3 support; generic foreign IDs need separate treatment. | Author-linked Zenodo image release, CC BY-SA 2.5. Preserve attribution, including Generated Photos. |
| [MIDV-500](https://zenodo.org/records/18504926) | 30.60 GiB | 50 source document types with capture frames, including a US passport card. Strong capture-condition coverage; limited independent identities. | CC BY-SA 2.5; retain individual source notices in the accompanying source table. |
| [MIDV-2019](https://zenodo.org/records/18761371) | 36.53 GiB | Additional distorted and low-light captures of MIDV-500 identities. | CC BY-SA 2.5; share identity groups with MIDV-500. |
| [MIDV-LAIT](https://zenodo.org/records/18781343) | 0.72 GiB | Indic, Perso-Arabic and Thai scripts, template text and capture geometry. | CC BY-SA 2.5; source attribution accompanies the archive. |
| [IDNet](https://arxiv.org/abs/2408.01690) | 361.34 GiB | Synthetic US licences/state ID and European identity documents; positive images and JSON metadata, plus fraud variants. | The eight pinned Zenodo records explicitly declare CC0 in their API metadata. |
| [CORD v2](https://github.com/clovaai/cord) | 2.15 GiB | 1,000 Indonesian receipts, selected word boxes/transcriptions and semantic hierarchy; future receipt parsing. | CC BY 4.0; official author-linked Hugging Face revision pinned. |
| [DocILE](https://docile.rossum.ai/) | Not acquired | Business fields and line items; use annotated train/validation for local evaluation. Precomputed OCR is not independent truth. | Access token and research terms; request access first. Repository MIT license does not license the dataset. |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/work/) | Not acquired | Scanned forms, words and relations. | Official non-commercial research/education terms; underlying image rights also need assessment. |
| [XFUND](https://github.com/doc-analysis/XFUND) | Not acquired | Forms and relationships in seven languages. | CC BY-NC-SA 4.0; not automatically included in product CI. |
| [SROIE](https://rrc.cvc.uab.es/?ch=13&com=downloads) | Not acquired | Receipt OCR and key information extraction candidate. | Official download endpoint timed out during research; terms not verified. |
| [SIDTD](https://doi.org/10.1038/s41597-024-04160-9) | Not acquired | Forgery evaluation derived from MIDV-2020. | Dataset terms still to verify. Fraud classes alone are not OCR ground truth. |

The [current author index](https://smartengines.ru/science/dataset/) links to
Zenodo. This supersedes our earlier assumption that MIDV-2020 could only be
obtained through the university request form. The pinned image release is
smaller than the older 124 GB distribution; raw TIFF/video variants mentioned in
the original README are not part of these eight published files.

IDNet layouts moved between archive parts across versions. For example, the
pinned part 4 contains AZ and WI, whereas the paper's original part 4 link
contained AZ and NC. The catalog uses the actual archive manifests, not the
paper's old part-to-state table. The similarly named IDNet-2025 Hugging Face
release contains European layouts and is not a substitute for the US files.

No suitable openly licensed image/field collection covering all PAN, Aadhaar,
Indian DL, voter ID, NREGA and NPR profiles was verified. Indic-script text is
useful recognition data, but it does not establish these document profiles'
accuracy. W-9, I-94, green-card and EAD coverage also remains unmeasured.

## Fetch and verify only the sample

```bash
python -m benchmarks.public_data list
python -m benchmarks.public_data fetch-samples
python -m benchmarks.public_data verify-samples --output benchmark-data/samples-report.json
```

The default root is ignored `benchmark-data/samples/`. No credentials or optional
Parquet dependency are needed. Only catalog, manifest, tooling and aggregate
reports belong in Git. Preserve dataset attribution and source notices; imported
data is not covered by the project's MIT license.

The fetcher has a fixed 100 MiB ceiling for both selected uncompressed files and
estimated bounded transfers. TAR/ZIP members are fetched using exact HTTP byte
ranges; a server returning a whole archive is rejected before reading its body.
ZIP members are decompressed with an output limit. Every file must match its
frozen size and SHA-256 before it is saved. Reruns reuse verified files; a corrupt
existing file fails instead of being silently replaced. There is no bulk-fetch
command. Run one sample writer per root.

CORD uses the official [single-row viewer API](https://huggingface.co/docs/dataset-viewer/en/rows).
The viewer's JPEG is a derivative of the original PNG; this sample explicitly
benchmarks that JPEG. Its labels were compared to the pinned source Parquet
records. Signed image URLs are resolved afresh; the source revision and hashes
must still match. Viewer changes fail closed and require a reviewed manifest
update, never a fallback to downloading a full shard.

`verify-samples` checks file hashes, image decoding, annotation parsing and
source-specific joins. It does **not** call OCR or claim accuracy. The checked
[integrity report](reports/public-data/samples.json) fingerprints the manifest.

## Historical source quality findings

These audits were performed during the earlier bulk research pass. Full source
archives are no longer retained and are not fetched by our tools. The aggregate
reports are retained for provenance, rather than repeated in ordinary CI.

- CORD: 800 train / 100 validation / 100 test images; 23,909 annotated words.
  Two duplicate image records within training and 19 out-of-bounds word boxes
  need an explicit curation decision. Preserve source labels and record any
  correction/exclusion separately. CORD's metadata calls validation `valid`;
  the adapter checks that documented mapping.
- MIDV-LAIT: 180 labeled templates and 3,600 capture frames; 2,015 text fields.
  All ZIP CRCs pass, but Pillow fails to decode one source template
  (`irn_passport_01.png`). Do not silently enable truncated-image loading.
- MIDV-2020 upright scans: all 1,000 image/annotation pairs join to the 1,000
  template identities. Templates supply 13,393 nonblank field annotations.
  Of 800 passport MRZ-line labels, 799 have length 44 and one has length 43.
  That anomaly requires review rather than automatic repair with our parser.
  One Azerbaijan template/scan pair was also visually checked for correspondence;
  this is not a manual audit of every label. All 1,000 photos also decode and
  join to template labels, as do all 1,000 rotated scans. All 68,409 clip frame filenames join to their
  annotations and the 1,000 identity groups; clip frames were not individually
  decoded in that structural audit.
- IDNet South Dakota: all 5,979 original images decode and pair with both the
  original-image annotations and basic semantic metadata. The entire ZIP passes
  CRC validation. All 15 basic metadata keys are present/nonblank across the
  original records; that does not imply all 15 values are printed on the card.
  One sample's name, licence number and dates were visually checked. Original
  annotation keys include `.png`; basic metadata filenames use `.json`.
  The other US layouts and fraud-image semantics are not covered by this audit.

Inspection results describe dataset quality, not OCR quality. Archive downloads
can be complete while labels or images still need curation. Current aggregate
reports are stored under `benchmarks/reports/public-data/`.

## Further regression and improvement measurements

1. Review label anomalies and implement source-specific adapters. Preserve raw
   truth; separately document date/name normalization, absent fields and every
   exclusion. Do not create expected answers by running the OCR under test.
   A template value does not prove that a field is visible in a particular
   capture; give clipped/occluded frames explicit partial/rejection expectations.
2. Freeze the regression sample and keep a separate evaluation holdout. This is
   evaluation only; there is no model-training pipeline. Group all views of an identity
   together, including MIDV-derived datasets and IDNet's repeated synthetic face
   identities across layouts. Keep original publisher split names visible and hash both
   assets and labels. Public pretrained models may have seen these datasets;
   retain a separate consented/private holdout for generalization claims.
3. Evaluate recognition, extraction and routing separately. Recognition uses
   annotated regions, CER/WER and localization metrics; CORD is not a complete
   page transcript. Extraction uses exact identifier/date matches, per-field
   accuracy and complete-record accuracy. Routing measures classification,
   rejection and false success. Report timeouts, crashes and p50/p95 latency.
4. Run base and candidate commits on the same immutable manifest, model hashes,
   dependency lock and hardware configuration. Refuse a comparison when corpus,
   labels, scoring version or model configuration differ unexpectedly. Model
   upgrades should have an explicit comparison mode that still freezes data.
5. Report newly failing/passing opaque case IDs, percentage-point change and
   error-count reduction by document type, issuer, script and capture condition.
   Gate critical-identifier regressions per case as well as aggregate changes;
   improvements elsewhere must not hide them. Show sample counts and independent
   identity counts; add uncertainty estimates grouped by identity.
6. Trigger a small reviewed corpus on changes to `core/`, model configuration,
   dependency locks and API preprocessing. Expand the sample only when a specific coverage gap justifies it, through a
   reviewed manifest change. Upload aggregate reports and a comparison summary, not document
   images/PII, to CI artifacts. Never auto-update an accepted baseline from a PR.

The existing passport/KYC/structured release gates remain intact. A public subset
report must not relax their full-profile coverage requirements or imply that an
unsupported document family has become supported. After the data/adapters are
reviewed, add the image-based workflow; the current unit-test CI tests
the bounded sample acquisition and scoring code. The local
`python -m benchmarks.public_accuracy` runner now records the initial baseline.
