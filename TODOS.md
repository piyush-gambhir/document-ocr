# TODOs

## 1. Model download error handling
**What:** Add try/except around PaddleOCR model initialization in `core/ocr_engine.py:_get_ocr()`.
**Why:** If HuggingFace is unreachable or disk is full, the first request hangs silently until timeout. Should raise a clear `MODEL_INIT_FAILED` error.
**Where to start:** `core/ocr_engine.py`, the `_get_ocr()` function. Wrap the `PaddleOCR(...)` call in try/except, catch `Exception`, log, and raise a custom error.

## 2. Lambda deployment
**What:** Create `deploy/lambda/Dockerfile.lambda` and restore `handler.py` + `template.yaml` for AWS Lambda deployment.
**Why:** Lambda is a valid deployment target for lagyavisa but was deferred because QEMU + PaddlePaddle segfaults on cross-architecture builds. Must be built on native x86.
**Blocked by:** Docker deployment proven in production, accuracy targets validated.
**Where to start:** Restore `deploy/lambda/` from git history, create a `Dockerfile.lambda` based on `public.ecr.aws/lambda/python:3.12`, test with `sam local invoke` on an x86 machine.

## 3. Clean sample passport images
**What:** Replace the watermarked sample images (`SAMPLE - IMMIHELP.COM`) with clean, anonymized/synthetic test passports.
**Why:** The watermark corrupts MRZ OCR output, making accuracy benchmarks unreliable. Cannot validate the 97% accuracy target with current samples.
**Options:** Generate synthetic passport images with PIL/reportlab, or source properly anonymized samples.
**Where to start:** `sample-passports/` directory. `benchmarks/accuracy.py` runs against these.

## 4. Tier 2 tests — TypeScript SDK
**What:** Add integration tests for the TS SDK: `scan()` with a mock HTTP server, retry on 5xx, timeout handling, AbortSignal propagation, `normalizeToBlob()`.
**Why:** The SDK's scan/retry/timeout behavior has 0 test coverage. These are real codepaths that every consumer hits.
**Depends on:** Tier 1 Python tests landing first.
**Where to start:** `tests/typescript/`, use vitest with a mock HTTP server (msw or similar).

## 5. Integrate into lagyavisa
**What:** Replace `TesseractOcrProvider` in lagyavisa backend with a new `PaddleOcrProvider` that calls the passport-ocr Docker service via the TypeScript SDK.
**Why:** This is the whole reason the passport-ocr repo exists — PaddleOCR >> Tesseract for passport accuracy.
**Depends on:** Docker deployment working, accuracy validated with clean samples.
**Where to start:** `lagyavisa/backend/src/modules/ocr/providers/`. The existing `OcrProvider` interface makes this a clean swap. Install the `passport-ocr` npm package, create `paddle-ocr.provider.ts`.
