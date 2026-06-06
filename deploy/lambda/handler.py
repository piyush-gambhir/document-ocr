"""
AWS Lambda handler for the document OCR pipeline.

Designed for the `document-ocr` npm SDK's `mode: 'lambda'` path
(`packages/passport-ocr/src/client.ts::invokeLambda`), which invokes the
function with a payload of `{"image_base64": "..."}` and expects either:

  * a raw scan-result object (returned directly), or
  * an `{"statusCode": N, "body": "<json>"}` envelope (body parsed; a 400
    throws `body.error`).

So this handler returns the raw `result.to_dict()` on a successful pipeline run
(any status, including a `failure` result) and the `{statusCode, body}` envelope
for input / model / internal errors. The envelope shape is also API-Gateway
(proxy integration) compatible.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from core.ocr_engine import OCRModelInitError
from core.pipeline import scan
from core.preprocessor import ImageQualityError

logger = logging.getLogger("document-ocr.lambda")
logging.getLogger().setLevel(logging.INFO)

MAX_DECODED_SIZE = 10 * 1024 * 1024  # 10 MB, matches the FastAPI server


def _error(status_code: int, code: str):
    return {"statusCode": status_code, "body": json.dumps({"error": code})}


def _extract_image_base64(event) -> str | None:
    """Pull image_base64 from a direct-invoke event or an API Gateway event."""
    if not isinstance(event, dict):
        return None
    if isinstance(event.get("image_base64"), str):
        return event["image_base64"]
    # API Gateway proxy integration: payload arrives JSON-encoded in `body`.
    body = event.get("body")
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, dict) and isinstance(parsed.get("image_base64"), str):
            return parsed["image_base64"]
    return None


def handler(event, context=None):
    image_base64 = _extract_image_base64(event)
    if not image_base64:
        return _error(400, "MISSING_IMAGE")

    try:
        data = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        return _error(400, "INVALID_BASE64")

    if len(data) == 0:
        return _error(400, "EMPTY_FILE")
    if len(data) > MAX_DECODED_SIZE:
        return _error(400, "FILE_TOO_LARGE")

    try:
        result = scan(data)
    except OCRModelInitError:
        logger.exception("model_init_failed")
        return _error(503, "MODEL_INIT_FAILED")
    except ImageQualityError as exc:
        return _error(400, str(exc))
    except Exception:
        logger.exception("internal_error")
        return _error(500, "INTERNAL_ERROR")

    payload = result.to_dict()
    logger.info(
        "status=%s page_type=%s confidence=%s processing_ms=%s",
        payload.get("status"),
        payload.get("pageType"),
        payload.get("confidence"),
        payload.get("processingMs"),
    )
    # Raw result for direct invoke (the SDK returns it as-is).
    return payload
