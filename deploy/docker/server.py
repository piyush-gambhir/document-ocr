"""
FastAPI server wrapping the passport OCR pipeline.

Used by the document-ocr npm package to run OCR locally.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import secrets
import uuid
from functools import partial
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, UploadFile, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, Response

from core.kyc_ocr import KycOCRConfigError
from core.ocr_engine import OCRModelInitError
from core.pipeline import scan
from core.document_bundle import scan_batch, scan_document
from core.document_registry import list_document_profiles, validate_document_hint
from core.barcodes import barcode_decoder_available
from core.jobs import configured_store
from core.redaction import redact, render_preview
from core.preprocessor import ImageQualityError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
SCAN_TIMEOUT_SECONDS = 60.0
logger = logging.getLogger("document-ocr")
# Matches the sibling pdf-worker service so a deployment sets one variable name
# everywhere. Unset means no auth is enforced, which is what local development wants.
API_TOKEN = os.getenv("API_TOKEN") or None

_ocr_semaphore = asyncio.Semaphore(1)
_models_ready = False
_model_init_error: str | None = None

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _models_ready, _model_init_error
    _models_ready = False
    _model_init_error = None
    logger.info("Loading OCR models...")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _warm_up_ocr)
    except (OCRModelInitError, KycOCRConfigError) as exc:
        # Stay up so /ready and /scan can report a clear error instead of the
        # process crash-looping. Liveness (/health) remains green.
        _model_init_error = str(exc)
        logger.error("OCR model initialisation failed: %s", exc)
    else:
        _models_ready = True
        logger.info("OCR models loaded.")
    yield


app = FastAPI(title="Document OCR", version="3.1.0", lifespan=_lifespan)


@app.middleware("http")
async def _private_responses(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _warm_up_ocr():
    from core.kyc_ocr import configured_kyc_languages
    from core.ocr_engine import _get_ocr

    for language in dict.fromkeys(("en", *configured_kyc_languages())):
        _get_ocr(language)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    if _model_init_error is not None:
        return JSONResponse(
            status_code=503,
            content={"status": "model_init_failed", "error": _model_init_error},
        )
    if not _models_ready:
        return JSONResponse(status_code=503, content={"status": "loading"})
    return {"status": "ready"}


def _scan_finished(future: asyncio.Future) -> None:
    _ocr_semaphore.release()
    # Consume late exceptions after a disconnected/timed-out caller has gone.
    if not future.cancelled():
        future.exception()


def _authorize(authorization):
    if API_TOKEN is not None:
        expected = f"Bearer {API_TOKEN}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="UNAUTHORIZED", headers={"WWW-Authenticate": "Bearer"})


async def _upload(image: UploadFile) -> bytes:
    content_type = image.content_type or ""
    if not content_type.startswith("image/") and content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="INVALID_CONTENT_TYPE")
    data = await image.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="FILE_TOO_LARGE")
    if not data:
        raise HTTPException(status_code=400, detail="EMPTY_FILE")
    return data


async def _uploads(images: list[UploadFile]) -> list[bytes]:
    if not 1 <= len(images) <= 10:
        raise HTTPException(status_code=400, detail="INVALID_BATCH_SIZE")
    output, size = [], 0
    for image in images:
        data = await _upload(image)
        size += len(data)
        if size > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail="BATCH_TOO_LARGE")
        output.append(data)
    return output


def _options(document_type, country, include_evidence):
    try:
        document_type, country = validate_document_hint(document_type, country)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Omit defaults for compatibility with one-argument pipeline integrations.
    return {key: value for key, value in {
        'document_type': document_type, 'country': country,
        'include_evidence': include_evidence,
    }.items() if value}


async def _execute(function, *args, **kwargs):
    request_id = str(uuid.uuid4())[:8]
    try:
        deadline = asyncio.get_running_loop().time() + SCAN_TIMEOUT_SECONDS
        await asyncio.wait_for(_ocr_semaphore.acquire(), timeout=SCAN_TIMEOUT_SECONDS)
        try:
            future = asyncio.get_running_loop().run_in_executor(None, partial(function, *args, **kwargs))
        except BaseException:
            _ocr_semaphore.release()
            raise
        future.add_done_callback(_scan_finished)
        return await asyncio.wait_for(asyncio.shield(future), timeout=max(0, deadline - asyncio.get_running_loop().time()))
    except asyncio.TimeoutError:
        logger.warning("[%s] scan_timeout", request_id)
        return JSONResponse(status_code=504, content={"error": "SCAN_TIMEOUT"})
    except OCRModelInitError:
        logger.error("[%s] model_init_failed", request_id)
        return JSONResponse(status_code=503, content={"error": "MODEL_INIT_FAILED"})
    except KycOCRConfigError:
        logger.error("[%s] invalid_kyc_ocr_config", request_id)
        return JSONResponse(status_code=503, content={"error": "INVALID_KYC_OCR_CONFIG"})
    except (ImageQualityError, ValueError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        logger.exception("[%s] internal_error", request_id)
        return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR"})


@app.post("/scan")
async def scan_passport(
    image: UploadFile = File(...), authorization: str | None = Header(default=None),
    document_type: str | None = Form(default=None), country: str | None = Form(default=None),
    include_evidence: bool = Form(default=False),
):
    _authorize(authorization)
    options = _options(document_type, country, include_evidence)
    result = await _execute(scan, await _upload(image), **options)
    if isinstance(result, Response):
        return result
    logger.info("status=%s page_type=%s confidence=%s processing_ms=%s", result.status,
                result.page_type, result.confidence, result.processing_ms)
    return JSONResponse(status_code=422 if result.status == 'failure' else 200, content=result.to_dict())


@app.get("/documents")
async def documents(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return {"schemaVersion": 1, "documents": list_document_profiles(),
            "capabilities": {"barcode": barcode_decoder_available(), "jobs": await asyncio.to_thread(_job_store, required=False) is not None,
                             "review": True, "multipage": True}}


@app.post("/scan/batch")
async def batch(
    images: list[UploadFile] = File(...), authorization: str | None = Header(default=None),
    document_type: str | None = Form(default=None), country: str | None = Form(default=None),
    include_evidence: bool = Form(default=False),
):
    _authorize(authorization)
    options = _options(document_type, country, include_evidence)
    return await _execute(scan_batch, await _uploads(images), **options)


@app.post("/scan/document")
async def grouped_document(
    images: list[UploadFile] = File(...), authorization: str | None = Header(default=None),
    document_type: str | None = Form(default=None), country: str | None = Form(default=None),
    include_evidence: bool = Form(default=False),
):
    _authorize(authorization)
    options = _options(document_type, country, include_evidence)
    return await _execute(scan_document, await _uploads(images), **options)


@app.get("/review", response_class=HTMLResponse)
async def review():
    import core
    path = Path(core.__file__).with_name('review.html')
    return HTMLResponse(path.read_text(), headers={'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; img-src 'self' blob: data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})


@app.post("/preview")
async def preview(image: UploadFile = File(...), authorization: str | None = Header(default=None)):
    _authorize(authorization)
    result = await _execute(render_preview, await _upload(image))
    if isinstance(result, Response):
        return result
    return Response(result, media_type='image/png', headers={'Cache-Control': 'no-store'})


@app.post("/redact")
async def redacted(image: UploadFile = File(...), boxes: str = Form(...), authorization: str | None = Header(default=None)):
    _authorize(authorization)
    if len(boxes) > 50000:
        raise HTTPException(status_code=400, detail='INVALID_REDACTION_BOXES')
    result = await _execute(redact, await _upload(image), boxes)
    if isinstance(result, Response):
        return result
    return Response(result, media_type='image/png', headers={'Cache-Control': 'no-store',
        'Content-Disposition': 'attachment; filename="redacted.png"'})


def _job_store(*, required=True):
    try:
        store = configured_store()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail='INVALID_JOB_CONFIGURATION') from exc
    if required and store is None:
        raise HTTPException(status_code=503, detail='JOBS_NOT_CONFIGURED')
    return store


@app.post('/jobs', status_code=202)
async def enqueue_job(
    images: list[UploadFile] = File(...), authorization: str | None = Header(default=None),
    document_type: str | None = Form(default=None), country: str | None = Form(default=None),
    include_evidence: bool = Form(default=False), grouped: bool = Form(default=False), notify: bool = Form(default=False),
):
    _authorize(authorization)
    options = _options(document_type, country, include_evidence)
    store = await asyncio.to_thread(_job_store)
    data = await _uploads(images)
    try:
        return await asyncio.to_thread(store.enqueue, data, options, grouped=grouped, notify=notify)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/jobs/{identifier}')
async def job(identifier: str, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    store = await asyncio.to_thread(_job_store)
    result = await asyncio.to_thread(store.get, identifier)
    if result is None:
        raise HTTPException(status_code=404, detail='JOB_NOT_FOUND')
    return result


@app.delete('/jobs/{identifier}')
async def delete_job(identifier: str, authorization: str | None = Header(default=None)):
    _authorize(authorization)
    store = await asyncio.to_thread(_job_store)
    removed = await asyncio.to_thread(store.delete, identifier)
    if not removed:
        raise HTTPException(status_code=404, detail='JOB_NOT_FOUND')
    return {'deleted': True}
