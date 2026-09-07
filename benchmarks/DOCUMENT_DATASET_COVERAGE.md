# Dataset sources for every supported document

Research date: 2026-09-07. All **15 registered document types** are mapped in the
[machine-readable catalog](document_dataset_coverage.json). Every entry records
source links, label type, access limitations, remaining gaps and a small sample
plan. A listed candidate is **not** an admitted or downloaded benchmark.

For the later 22-image expansion and measured multi-document results, see
[the repeated evaluation](MULTIDOC_EVALUATION.md). This catalog records the original
research pass; its original readiness notes below are historical.

No new image datasets were downloaded in that research pass. The existing
40-image sample and its measured baseline remain unchanged. This is evaluation,
not model training; prefer a few independently labeled examples per variant.

| Registered profile | Best available source | Evaluation readiness |
| --- | --- | --- |
| Passport book | [MIDV-2020](https://zenodo.org/records/18786808), [MIDV-500](https://zenodo.org/records/18504926) | Non-Indian biodata covered by the existing sample. Indian passport and back-page gaps remain; see below. |
| PAN | [Jwalit KYC](https://huggingface.co/datasets/Jwalit/kyc-document-extraction-vlm), [PAN v5](https://www.kaggle.com/datasets/sparsh2002/pan-card-dataset/versions/5) | Candidates only: terms, provenance and exact field truth unresolved. |
| Aadhaar | [MIDV-LAIT](https://zenodo.org/records/18781343), Jwalit KYC | Paired multilingual template text available; not full valid-card/front/back/masked/QR coverage. |
| Indian driving licence | [Synthetic Indian DL](https://huggingface.co/datasets/NIDHISH1980/indian-driving-license-dataset) | Classification/quality candidate, not OCR field truth. Publisher warns generated text may be unreadable. |
| Voter ID | Jwalit KYC | Candidate only; no admitted independently labeled EPIC sample. |
| NREGA job card | [CoRE Stack](https://core-stack.org/datasets/) | Administrative metadata, not paired card images. Image dataset gap. |
| NPR letter | No suitable paired source verified | National Population Register letters need a new annotated collection. |
| US driver licence | [IDNet](https://arxiv.org/abs/2408.01690) | Paired synthetic data; five SD images already tested. Expand state/layout coverage selectively. |
| US state ID | IDNet / official references | Exact non-driver card coverage needs verification; licences cannot substitute for state IDs. |
| Passport card | [MIDV-500](https://zenodo.org/records/18504926), `48_usa_passportcard.zip` | Suitable source identified; small member/annotation sample not yet acquired. |
| US green card | [USCIS document references](https://www.uscis.gov/i-9-central/form-i-9-acceptable-documents) | Reference candidate only; current page retrieval returned 403. No paired corpus verified. |
| US EAD | USCIS document references | Same gap; I-765 application forms are not I-766 card samples. |
| Visa | Jwalit KYC, [MRV benchmark generator](https://github.com/over-geek/mrz-reader/blob/main/benchmark-dataset/README.md) | Terms/labels need review. Generator's MRV cases test unsupported formats in its own system. |
| US I-94 | [Official CBP sample](https://www.cbp.gov/sites/default/files/documents/CBP%20Form%20I-94%20English%20SAMPLE_Watermark.pdf) | Blank paper reference only. Completed electronic/paper records still need independent labels. |
| US W-9 | [Symage US Forms Preview](https://huggingface.co/datasets/Symage/synthetic-us-forms-preview) | Strong new candidate: 50 synthetic W-9 documents, field links/text/boxes, CC-BY-4.0. Clean renders only; inspect a small subset next. |

## Indian passport findings

There are leads, but no admitted positive Indian passport benchmark yet:

- [akashsalmuthe/ind_passport](https://huggingface.co/datasets/akashsalmuthe/ind_passport)
  advertises images/descriptions. The repository has an Arrow file but no
  dataset licence or annotation-provenance documentation. Exact MRZ/field
  fidelity is unverified. A similarly named repository from the same author
  must not be treated as an independent source.
- [UniData's Indian passport card](https://huggingface.co/datasets/ud-synthetic/indian-passports)
  advertises a larger synthetic product, but the actual pinned public repository
  contains **only CSV metadata and a README, no images**. Its NC-ND terms and
  provider-access requirements are recorded. It cannot supply our image test.
- [PRADO IND-AO-01001](https://www.consilium.europa.eu/prado/en/IND-AO-01001/index.html)
  is an official older-layout reference. [PRADO-specific reuse restrictions](https://www.consilium.europa.eu/en/about-site/copyright/)
  mean it stays a link, not an automatically collected fixture.
- [Commons](https://commons.wikimedia.org/wiki/Category:Passports_of_India)
  contains references, including blank and censored pages, with individual file
  licences. These have no paired labels and cannot establish complete positive
  extraction accuracy when fields have been removed.

The earlier MIDV-500 archive inventory has no Indian passport entry. The existing
European passport numbers must not be reported as Indian accuracy. No Indian
accuracy improvement has been measured, and no OCR tuning was made from these
unverified sources. An image set with independently checked fields is still
needed before the requested Indian baseline/fix/retest cycle can be completed.

## What qualifies for our evaluation suite

An admitted sample needs a usable image, independently checked expected values,
a documented source/revision and terms, and an identity group. Record expected
rejection for malformed, partial, blank or censored documents. Detection boxes,
generation prompts, model-produced descriptions and administrative/text-only
records are not substitutes for verified field values.

The source catalog keeps such leads because they explain what still needs work;
it does not expose a downloader for unresolved candidates. It also records
Roboflow Aadhaar detection and text-only Indian PII sources as limited-use leads.
Do not scrape accidentally exposed identity documents to fill coverage gaps.

Start with 5–10 reviewed examples per profile/variant, preserve independent holder
groups, and keep rare failures. Fetch only selected members/rows with pinned
hashes, following the existing bounded sample workflow. US W-9 and passport-card
samples are the next concrete public additions. Indian passport, full Indian KYC,
NPR/NREGA and immigration-card datasets still need source/annotation work.
