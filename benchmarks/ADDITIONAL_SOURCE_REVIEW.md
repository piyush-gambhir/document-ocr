# Additional document source review

Reviewed 2026-09-08. This is historical source research, not the active accuracy
suite. Dataset-only evaluation excludes the agent-transcribed EAD and locally
generated fixtures. This is a bounded follow-up to the
[15-profile source catalog](DOCUMENT_DATASET_COVERAGE.md). It adds one usable
official EAD specimen and keeps unresolved sources as links. No full dataset was
downloaded. Downloaded source payloads in this review total **1,212,384 bytes**:
one EAD image, one green-card reference image, and one single-page I-94 reference
PDF. Only the EAD image enters the new manifest.

## Admitted reviewed specimen

[USCIS EAD card](https://commons.wikimedia.org/w/index.php?title=File:USCIS_EAD_card.jpg&oldid=916147826)
is a 2,003 × 1,278, 505,084-byte original JPEG attributed to U.S. Citizenship and
Immigration Services. Commons records it as a U.S. federal government public-domain
work, published by USCIS in July 2017 and uploaded to Commons in March 2019. Its
[linked USCIS image](https://www.uscis.gov/sites/default/files/USCIS/E-Verify/Images/4.2_Figure_3_Auto_Extend_EAD.jpg)
did not resolve during this review, so the hash-pinned Commons original is the
download source. “2017” in our identifier describes that publication metadata;
it is not a claim that the image depicts the redesigned 2017 EAD layout.

The image is a completed, fictional `SPECIMEN / TEST V` card front. Ten printed
fields were transcribed by the reviewing agent **before inspecting OCR output**.
The checked-in [truth file](specimen_truth/uscis-ead-2017.json) records the
normalizations and historical two-digit date interpretation. These are **agent
visual transcriptions**, not publisher-supplied field annotations or an independent
human double review. They provide a reviewed specimen contract check; they cannot
establish population accuracy. The admitted manifest has one source-document
group and one untouched front image, with no back or additional card design.
HTTP checks may re-encode that same image as PNG, JPEG or an image-only PDF;
these are derived inputs, not newly acquired specimens or independent identities.
Its expired dates are preserved: this evaluates extraction, not immigration
eligibility or authenticity.

The [new manifest](additional_profile_samples.json) pins the untouched image and
checked-in truth by SHA-256 and byte count. It contains 506,150 bytes including
truth. The preparation command copies the reviewed truth to the ignored sample
directory and optionally downloads only the one missing image:

The optional preparation tool and manifest remain in the repository as research
material; they are not invoked by current accuracy CI.

The preparation command refuses changed source bytes. Do not update hashes to
accept an unexplained changed download. Review both image and labels explicitly.
The separate one-specimen policy requires three repeats and all ten fields to
match. Its absolute gate remains failed while any field is wrong; a passing
relative comparison only establishes no regression against the paired baseline.

The label file remains fixed while OCR recovery changes. An enhanced versus
unenhanced read can disagree on this specimen's given name; such a conflict
retains a failure status and is exposed through `OCR_VIEW_CONFLICT_GIVEN_NAMES`.
Request `include_evidence=True` to inspect both observed readings. Neither
joined-label parsing nor a pixel reread authorizes inserting expected name
characters or changing the transcription to match the model. The
[recovery notes](REMAINING_RECOVERY_NOTES.md) describe those safeguards; the
[all-document report](ALL_DOCUMENTS_EVALUATION.md) contains the dated measurements
and remaining failures.

## Sources reviewed but not admitted as positive accuracy evidence

| Profiles | Source and finding | Remaining requirement |
| --- | --- | --- |
| Indian PAN, Aadhaar, voter ID, passport, visa | [Jwalit KYC](https://huggingface.co/datasets/Jwalit/kyc-document-extraction-vlm) exposes images with chat-form responses. The reviewed card does not establish an image licence, consent/provenance, or independent field verification. Chat answers are not adopted as truth. | Document image rights and independently reviewed labels before selecting individual rows. |
| Indian passport | [akashsalmuthe/ind_passport](https://huggingface.co/datasets/akashsalmuthe/ind_passport) remains an image/description lead without verified dataset licensing and label provenance. The previously reviewed PRADO/UniData limitations remain. | An admitted positive Indian passport specimen or consented collection with labels. |
| Indian driving licence | [NIDHISH1980 synthetic DL](https://huggingface.co/datasets/NIDHISH1980/indian-driving-license-dataset) has 30 diffusion-generated images. Publisher metadata describes prompts and capture styles, and explicitly warns generated text may not be readable or accurate. Its card also states research/education-only use. | Rights suitable for the intended use and field transcriptions checked against the actual pixels. Prompt values are not OCR ground truth. |
| NREGA job card | [CoRE Stack datasets](https://core-stack.org/datasets/) describes GIS/administrative data and NREGA assets, not paired job-card images. | Small consented or explicitly licensed card-image collection. |
| NPR letter | No suitable paired, licensed image-and-field source was verified in this follow-up. | A completed letter specimen plus verified printed values; text records do not substitute. |
| US state ID | Existing [IDNet](https://arxiv.org/abs/2408.01690) licence coverage cannot be relabelled as non-driver state-ID coverage. No new non-driver specimen was admitted. | Confirm actual card type and corresponding publisher truth before fetching selected members. |
| US green card | [USCIS 2023 comparison mirrored on Commons](https://commons.wikimedia.org/w/index.php?title=File:United_States_Green_Card_(2023_edition).jpg&oldid=911789236) is 804 × 836 overall, but the actual front occupies only about 495 × 313 pixels and includes callout overlays plus a second side. The [clean 2023 front](https://commons.wikimedia.org/wiki/File:2023_green_card_front.jpg) is only 600 × 378. The [2017 composite](https://commons.wikimedia.org/wiki/File:2017-us-green-card-specimen.png) is 430 × 602 across both sides. These are public-domain reference leads, not new full-card positive fixtures. | Obtain a sufficiently resolved original single side, preserve clear labels and layout provenance. Do not upscale a thumbnail and count it as new image evidence. |
| US I-94 | A [one-page CBP quick reference mirrored by the Czech foreign ministry](https://mzv.gov.cz/public/de/84/fa/1026818_955439_I_94_example1.pdf) was rendered and inspected. It contains several small paper records, handwriting, a crossed-out admission number, a private law-office overlay and no paired transcription. The [CBP fact-sheet endpoint](https://www.cbp.gov/document/fact-sheets/i-94-fact-sheet) returned 403. | Obtain a completed clear electronic or paper specimen with unambiguous field truth and suitable source provenance. Keep ambiguous crossed-out values out of a positive exact-match gate. |
| Visa | [EU official-journal visa specimen](https://commons.wikimedia.org/wiki/File:Schengenvisum-specimen.jpg) is a legal-layout reference; no paired completed identity truth was established. Personally uploaded visa scans are not silently collected to fill coverage. | A clearly licensed completed specimen with verified MRV/visual fields. |

Passport books outside India, South Dakota licences, passport cards and W-9 forms
retain the admitted public samples described in
[MULTIDOC_EVALUATION.md](MULTIDOC_EVALUATION.md). No population or state coverage
is inferred from their small fixed source-document groups. The four US
passport-card captures share one MIDV-500 specimen. The handheld `HS/01` source
image's blur rejection belongs to that existing public sample; it is unrelated
to this EAD specimen's name conflict. Keeping that rejected view in its public
denominator does not require acquiring or altering another image.

[Indic synthetic profiles](https://huggingface.co/datasets/adwaith06/indic-synthetic-profiles)
is a useful MIT-licensed **text/tabular** lead, with generated Indian names and
identifiers. It has no document images. Rendering explicit fictional inputs
locally is useful for all-profile contracts, but those scores must remain separate
from the admitted public annotated corpus and this reviewed EAD. The project's
[local generator](synthetic_documents.py) defines its own fictional inputs;
this text-only lead is not an additional image sample or annotation source for
the current manifest. More repetitions, transformations, or HTTP submissions
do not create more independent identities.

The remaining gaps are data gaps, not proof that extraction works. Generated
fixtures are excluded from the active evaluation. Representative accuracy claims
require a small independently annotated dataset holdout for each actual layout.
