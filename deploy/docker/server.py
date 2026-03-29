"""
FastAPI server wrapping the passport OCR pipeline.

Used by the passport-ocr npm package to run OCR locally.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from core.pipeline import scan
from core.preprocessor import ImageQualityError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
logger = logging.getLogger("passport-ocr")

_ocr_semaphore = asyncio.Semaphore(1)
_models_ready = False

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Passport OCR", version="1.0.0")


@app.on_event("startup")
async def _load_models():
    global _models_ready
    logger.info("Loading OCR models...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _warm_up_ocr)
    _models_ready = True
    logger.info("OCR models loaded.")


def _warm_up_ocr():
    from core.ocr_engine import _get_ocr
    _get_ocr("en")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    if not _models_ready:
        return JSONResponse(status_code=503, content={"status": "loading"})
    return {"status": "ready"}


@app.post("/scan")
async def scan_passport(image: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]

    # Validate content type
    content_type = image.content_type or ""
    if not content_type.startswith("image/") and content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="INVALID_CONTENT_TYPE")

    # Read and check size
    data = await image.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="FILE_TOO_LARGE")

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="EMPTY_FILE")

    # Run pipeline
    try:
        async with _ocr_semaphore:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, scan, data),
                timeout=60.0,
            )
    except asyncio.TimeoutError:
        logger.warning(f"[{request_id}] scan_timeout")
        return JSONResponse(status_code=504, content={"error": "SCAN_TIMEOUT"})
    except ImageQualityError as e:
        logger.info(f"[{request_id}] quality_error={e}")
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:
        logger.exception(f"[{request_id}] internal_error")
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR"},
        )

    # Log only non-PII fields
    logger.info(
        f"[{request_id}] status={result.status} "
        f"page_type={result.page_type} "
        f"confidence={result.confidence} "
        f"processing_ms={result.processing_ms} "
        f"errors={result.errors}"
    )

    if result.status == "failure":
        return JSONResponse(status_code=422, content=result.to_dict())

    return result.to_dict()
