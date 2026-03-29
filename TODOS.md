# TODOs

## 1. Model download error handling
**What:** Add try/except around RapidOCR model initialization in `core/ocr_engine.py:_get_ocr()`.
**Why:** If ModelScope is unreachable or disk is full, the first request hangs silently until timeout. Should raise a clear `MODEL_INIT_FAILED` error.
**Where to start:** `core/ocr_engine.py`, the `_get_ocr()` function. Wrap the `RapidOCR(...)` call in try/except, catch `Exception`, log, and raise a custom error.

## 2. Lambda deployment
**What:** Create `deploy/lambda/Dockerfile.lambda` and `handler.py` + `template.yaml` for AWS Lambda deployment.
**Why:** Lambda is a valid deployment target. RapidOCR + ONNX Runtime is small enough for Lambda container images (~500MB).
**Where to start:** Create `deploy/lambda/` directory with a Dockerfile based on `public.ecr.aws/lambda/python:3.12`, test with `sam local invoke`.

## 3. Clean sample passport images
**What:** Replace the watermarked sample images (`SAMPLE - IMMIHELP.COM`) with clean, anonymized/synthetic test passports.
**Why:** The watermark corrupts some OCR output, making accuracy benchmarks less reliable. Cannot fully validate accuracy targets with current samples.
**Options:** Generate synthetic passport images with PIL/reportlab, or source properly anonymized samples.
**Where to start:** `sample-passports/` directory. `benchmarks/accuracy.py` runs against these.

## 4. TypeScript SDK tests
**What:** Add integration tests for the TS SDK: `scan()` with a mock HTTP server, retry on 5xx, timeout handling, AbortSignal propagation, `normalizeToBlob()`.
**Why:** The SDK's scan/retry/timeout behavior has minimal test coverage.
**Depends on:** Python pipeline tests passing.
**Where to start:** `tests/typescript/`, use vitest with a mock HTTP server (msw or similar).

## 5. Back page extraction accuracy
**What:** Improve the back page field extraction accuracy in `core/back_page_extractor.py`.
**Why:** The current spatial label→value extraction works but misses some fields depending on OCR text segmentation. Father name, spouse name, and address extraction need tuning.
**Where to start:** `core/back_page_extractor.py`, test with sample-indian-passport-2.jpg.

## 6. Cloud Run deployment
**What:** Add a `deploy/cloudrun/` config with `cloudbuild.yaml` or document `gcloud run deploy` steps.
**Why:** Cloud Run is the recommended free-tier deployment target. The Docker image is ready but deployment steps aren't documented.
**Where to start:** Document the `gcloud run deploy` command in README or create a deploy script.
