# TODOs

_The original six items (model-init error handling, Lambda deploy, clean sample
images, TypeScript SDK tests, back-page accuracy, Cloud Run deploy) were
completed in 1.2.0 — see CHANGELOG.md._

## Multi-document follow-ups

1. **Deskew in the preprocessor (biggest accuracy lever).** The end-to-end KYC
   benchmark (`make benchmark-documents`) scores 100% on clean images but drops to
   ~82–88% under a ±3° rotation, because `core/preprocessor.py` only does
   document-boundary perspective correction, not text-line deskew. Adding a Hough/
   projection-profile deskew step would recover most of the rotation loss (and
   help real-world phone photos). This is the clearest robustness win.

2. **Passport probe over-eagerly claims KYC cards.** The cheap bottom-crop
   passport probe (`core/pipeline._extract_targeted_regions` + `classify_passport_page`)
   treats "SEX" and "DATE OF BIRTH" as biodata hints, so a voter/DL card showing
   those exact labels in its lower ~55% can mis-route to the passport path before
   `classify_document` ever runs. The synthetic voter cards dodge this by using
   "Gender"/"DOB", but real cards won't. Fix: require an MRZ (or a passport
   keyword) before committing to the passport path, or run `classify_document`
   first and only treat as passport when it agrees.

3. **Real sample images for the new document types.** We now have synthetic
   labelled specimens + an end-to-end benchmark (`sample-documents/`,
   `benchmarks/document_accuracy.py`). The remaining gap is *real* scans — add
   anonymized real PAN/Aadhaar/DL/voter images with ground-truth labels to
   measure true-world (not just rendered) accuracy.

5. **Driving licence layout variance.** The DL extractor is best-effort; layouts
   differ substantially by issuing state. Gather fixtures from more states
   (especially Smart Card DLs and the newer Parivahan format) and tune
   `core/driving_licence_extractor.py`. The DL identifier format check in
   `core/validators.py` is also loose — tighten per-state if needed.

6. **Aadhaar name detection.** Aadhaar has no Latin label for the holder name, so
   `_find_name` infers it spatially relative to the DOB line. Validate against
   more real layouts (vertical/horizontal cards, masked Aadhaar, mAadhaar PDF).

7. **SDK retry semantics for 4xx.** `packages/passport-ocr/src/retry.ts` only
   skips retries when the error message contains `400`/`422`; a 400 whose body
   carries a non-numeric `error` (e.g. `INVALID_CONTENT_TYPE`) is still retried.
   Consider threading the HTTP status through instead of string-matching.

8. **Server lifespan handler.** `deploy/docker/server.py` still uses the
   deprecated `@app.on_event("startup")`; migrate to a FastAPI lifespan handler.
