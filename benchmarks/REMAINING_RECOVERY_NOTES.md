# Bounded OCR recovery and remaining limits

These changes address observed text, layout and image-recognition failures.
They use production OCR geometry and fresh pixel reads, without publisher
coordinates, fixture identifiers or expected answers. The
[all-document evaluation](ALL_DOCUMENTS_EVALUATION.md) contains dated accuracy
and latency measurements; the budgets below describe recovery operations, not
portable timing guarantees.

## Small passport inside a photograph

The additional MIDV-2020 Azerbaijan passport photo (`aze_passport/41/photo`)
previously returned `unsupported_page` despite legible MRZ pixels. The passport
occupies a small part of a tall photograph. Full-page detection saw only short
fragments. The existing focus crop revealed the beginning of the second MRZ
line, but recovery discarded it because the line had neither its full 44
characters nor enough filler characters.

[Passport recovery](../core/mrz_recovery.py) accepts a truncated second-line
anchor only when its observed document number, birth date and expiry date all
have valid check digits. It uses that anchor's text geometry to read the
remaining pixels, with a character of margin at either edge. The final result
still requires a complete MRZ with valid individual and composite checksums.
Missing identifiers, dates and check digits are never invented.

The focus crop and final band share a two-detection budget. Other paths retain
their existing limits of two band reads and, when needed, one recognition-only
header read per complete anchor. The earlier targeted probe recovered all eight
publisher-labeled fields and the exact MRZ pair; use the repeated report for
current timing and regressions. Neither that non-Indian passport nor the
[generated Indian contracts](synthetic_documents.py) establishes real Indian
passport accuracy.

Unicode compatibility normalization handles OCR output such as Roman numeral
`Ⅰ` through its defined Latin `I` equivalent. It does not replace arbitrary
letters using an expected country. [Travel recovery](../core/travel_recovery.py)
can reread an ambiguous TD3/visa row with two different crop margins, requiring
agreement and preserving already checked fields and plausible country codes.
It permits at most two recognitions per damaged row, up to four for one pair;
already complete, valid, plausible MRZ pairs need no additional travel reread.
Checksums do not protect issuer/nationality fields, so unresolved unknown codes
remain validation failures. Agreement between crops is still recognition by
the same model, not independent authentication.

## Joined labels and overlapping OCR boxes

The shared [structured-field parser](../core/structured_documents.py) recognizes
joined printed forms such as `ExpiresOn` and `USA` followed immediately by a
valid state code. `Expires` and `ISS` also act as field boundaries so another
field cannot borrow their values.

A label and its value may have slightly overlapping OCR boxes even though the
printed value is to the right. Association permits a small, bounded overlap
when the value's center is beyond the label's right edge. An intervening field
label blocks that association. For a value beneath a label, the top-edge center
is measured in the label's own axes: a long, slightly slanted value box should
not be rejected solely because its outer corner overlaps the label. These rules
use observed text and geometry. They do not add a missing date digit or move a value across another labeled
field. They are generic parser fixes, not substitutions for particular specimen
names, dates or identifiers.

## Passport-card front in clutter

The MIDV-500 `passportcard/CS/01` photograph initially had four correct fields.
Its card number was recognized, but the number label was misspelled; the expiry
label was absent and the expiry value lost its final digit. This differs from
a missing MRZ.

For an identified, incomplete US passport-card front,
[card recovery](../core/card_recovery.py) can reread one observed card-number
label directly from its pixels. The fresh label must be recognized exactly with
at least 0.9 confidence. If needed, one detector read of a small text cluster
uses the observed issuer heading and aligned nearby text to deskew the crop.
Only evidence for missing number/expiry fields is merged. Keeping unrelated
reread text out prevents a large specimen watermark from replacing a previously
correct name. The result must be complete, preserve existing values, agree with
the fresh field reads and provide at least 0.9 confidence for every added field.

A separate route handles a card whose **only missing required field is expiry**.
It requires one confident expiry label and one aligned, nearby truncated-date
region. An in-bounds crop adds five percent horizontal margin at each end and
is sent directly to the line recognizer, avoiding a detector rerun when that
read succeeds. A fresh complete date must parse correctly, preserve the entire
observed prefix and reach at least 0.9 confidence before admission.

A second direct read is conditional:

- A complete first read between 0.8 and 0.9 confidence may be reread after a
  3 × 3 median filter. The second read must reach 0.9 confidence and agree on
  the complete parsed date.
- A confident first read that repeats exactly the truncated prefix may instead
  be reread once at the same coordinates in the unenhanced image. That image
  must have the same dimensions; its complete date must preserve the prefix
  and reach 0.9 confidence.

Those alternatives cannot both run. This expiry step therefore uses **at most
two direct recognitions**. If the card is still incomplete, the existing issuer
text-cluster fallback can add **one detector call**, for at most three recovery
calls on this route. The number-missing route retains at most one label
recognition plus one cluster detection. Complete cards and unconfirmed profiles
incur no card-recovery reads. All admitted candidates must preserve existing
fields; a direct date read alone does not prove that the full API result passes.

The final targeted `scan(include_evidence=True)` check recovered all six
publisher-scored fields for the template's original, JPEG and image-only PDF
inputs, and for the existing table (`TA/01`) and clutter (`CS/01`) photographs.
These are format and capture checks of one specimen, not new identities or an
HTTP capacity measurement. Their local diagnostic score records deliberately
set `elapsedMs` to zero; use only the separate timed evaluations for latency.

The handheld `passportcard/HS/01` source image remains below the existing blur
threshold: an earlier diagnostic measured whole-frame Laplacian variance 76.95
against 80. Even diagnostic rectification using publisher corners measured
53.77. Production code does not consume those corners or lower the blur
threshold to accept this view. It stays in the public sample and its positive
field denominator as a quality rejection. This is a separate failure from the
EAD given-name conflict described below.

## PDF contrast without changing evidence coordinates

For PDFs, [the pipeline](../core/pipeline.py) keeps the renderer's coordinate
plane. Contrast enhancement is applied lazily when an image OCR pass is needed:
an image-only PDF takes that path immediately; a native-text PDF takes it only
if the native-text routing falls back to visible OCR. An accepted native-text
path avoids this extra image processing and retains its existing
`PDF_NATIVE_TEXT_NOT_VISUALLY_VERIFIED` warning.

[Contrast enhancement](../core/preprocessor.py) changes color values without
resizing, perspective correction or other geometry changes. The original-color
render is retained for permitted fallback reads at those same coordinates.
Preview dimensions, barcode/native-text boxes and returned OCR evidence therefore
continue to refer to the same page plane. Image-only PDFs have no text layer
that could supply fixture answers. Correctly reading a diagnostic crop is not
a substitute for rerunning the complete PDF API path and scoring its response.

## Historical USCIS EAD specimen

The [admitted EAD](ADDITIONAL_SOURCE_REVIEW.md) is one public-domain fictional
specimen with agent-transcribed fields. The `2017` in its fixture name refers
to source publication metadata, not a claim about the card's design edition.
It is not a representative EAD benchmark or an independently double-reviewed
annotation set.

Earlier controlled reads at the same image width found that CLAHE amplified
the specimen's security pattern. Reading the normalized image before enhancement
recovered the issuer heading and several field labels more clearly. The
[bounded EAD helper](../core/ead_recovery.py) can use one full unenhanced read for
an already identified, incomplete US EAD, and one direct read of an observed
truncated expiry label if needed. That fresh label must actually read `Card
Expires` with high confidence; code does not complete its spelling. The
historical two-digit years are interpreted by the date parser, with the
[reviewed truth](specimen_truth/uscis-ead-2017.json) retaining the original dates
and normalization rationale.

The known specimen failure is given-name disagreement between image views,
including spacing. It must not be repaired by inserting expected characters or
changing the frozen truth to match OCR. On a conflict, both observed readings
remain available with `include_evidence=True`, the response carries
`OCR_VIEW_CONFLICT_GIVEN_NAMES`, and failure status and capped confidence make
the need for review explicit. The helper also preserves pre-existing errors.
Default responses omit field evidence. Date extraction does not establish
immigration eligibility, document authenticity or current validity.

## Evaluation limits

The public passport-card views still share one source specimen; the reviewed
EAD still has one source-document group. PNG/JPEG/PDF conversions and repeated
requests are additional views or API checks, not independent identities.
Active accuracy results use publisher-annotated dataset samples only. Generated
contracts and this agent-reviewed specimen remain historical engineering and
research material outside the active evaluation. The [coverage guide](DOCUMENT_DATASET_COVERAGE.md)
records the remaining image, annotation, language and layout gaps. Diagnostic
images and raw OCR output remain in ignored `benchmark-data/`; final claims
must use the paired end-to-end reports and retain their unresolved failures.
