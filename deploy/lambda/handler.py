"""AWS direct invoke/API Gateway handler with bounded inline or allowlisted S3 input."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os

from core.kyc_ocr import KycOCRConfigError
from core.ocr_engine import OCRModelInitError
from core.pipeline import scan
from core.preprocessor import ImageQualityError
from core.document_registry import validate_document_hint

logger = logging.getLogger('document-ocr.lambda')
MAX_DECODED_SIZE = 10 * 1024 * 1024
MAX_ENCODED_SIZE = ((MAX_DECODED_SIZE + 2) // 3) * 4


def _response(status: int, payload: dict):
    return {'statusCode': status, 'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
            'body': json.dumps(payload)}


def _error(status_code: int, code: str):
    return _response(status_code, {'error': code})


def _event_payload(event):
    if not isinstance(event, dict):
        raise ValueError('MISSING_IMAGE')
    if 'body' not in event:
        return event, False
    body = event['body']
    if not isinstance(body, str):
        raise ValueError('INVALID_REQUEST_BODY')
    if len(body) > MAX_ENCODED_SIZE + 65536:
        raise ValueError('FILE_TOO_LARGE')
    try:
        if event.get('isBase64Encoded'):
            body = base64.b64decode(body, validate=True).decode('utf-8')
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('INVALID_REQUEST_BODY') from exc
    if not isinstance(parsed, dict):
        raise ValueError('INVALID_REQUEST_BODY')
    return parsed, True


def _read_s3(reference):
    if not isinstance(reference, dict):
        raise ValueError('INVALID_S3_REFERENCE')
    bucket, key = reference.get('bucket'), reference.get('key')
    version = reference.get('version_id')
    allowed_bucket, prefix = os.getenv('DOCUMENT_OCR_S3_BUCKET'), os.getenv('DOCUMENT_OCR_S3_PREFIX', '')
    if not allowed_bucket:
        raise ValueError('S3_NOT_CONFIGURED')
    if bucket != allowed_bucket or not isinstance(key, str) or not key or not key.startswith(prefix):
        raise ValueError('S3_OBJECT_NOT_ALLOWED')
    if version is not None and (not isinstance(version, str) or not version):
        raise ValueError('INVALID_S3_REFERENCE')
    # The execution role grants GetObject/GetObjectVersion only for this prefix.
    # S3 keys are opaque: no decoding, filesystem traversal or remote URL fetch.
    import boto3
    args = {'Bucket': bucket, 'Key': key}
    if version is not None:
        args['VersionId'] = version
    response = boto3.client('s3').get_object(**args)
    body = response['Body']
    try:
        if response.get('ContentLength', 0) > MAX_DECODED_SIZE:
            raise ValueError('FILE_TOO_LARGE')
        data = body.read(MAX_DECODED_SIZE + 1)
        if len(data) > MAX_DECODED_SIZE:
            raise ValueError('FILE_TOO_LARGE')
        return data
    finally:
        body.close()


def _read_image(payload):
    if 's3' in payload and 'image_base64' in payload:
        raise ValueError('AMBIGUOUS_IMAGE_SOURCE')
    if 's3' in payload:
        return _read_s3(payload['s3'])
    image = payload.get('image_base64')
    if not isinstance(image, str) or not image:
        raise ValueError('MISSING_IMAGE')
    if len(image) > MAX_ENCODED_SIZE:
        raise ValueError('FILE_TOO_LARGE')
    try:
        return base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('INVALID_BASE64') from exc


def handler(event, context=None):
    try:
        payload, gateway = _event_payload(event)
        document_type, country = validate_document_hint(payload.get('document_type'), payload.get('country'))
        evidence = payload.get('include_evidence', False)
        if not isinstance(evidence, bool):
            raise ValueError('INVALID_INCLUDE_EVIDENCE')
        data = _read_image(payload)
        if not data:
            raise ValueError('EMPTY_FILE')
        if len(data) > MAX_DECODED_SIZE:
            raise ValueError('FILE_TOO_LARGE')
        options = {k:v for k,v in {'document_type':document_type, 'country':country, 'include_evidence':evidence}.items() if v}
    except ValueError as exc:
        return _error(400, str(exc))
    except Exception:
        logger.error('input_read_failed')
        return _error(500, 'INPUT_READ_FAILED')
    try:
        result = scan(data, **options)
    except ImageQualityError as exc:
        return _error(400, str(exc))
    except OCRModelInitError:
        logger.error('model_init_failed')
        return _error(503, 'MODEL_INIT_FAILED')
    except KycOCRConfigError:
        return _error(503, 'INVALID_KYC_OCR_CONFIG')
    except Exception:
        # Cloud SDK errors may contain bucket/key details; do not log payloads.
        logger.error('scan_failed')
        return _error(500, 'INTERNAL_ERROR')
    output = result.to_dict()
    logger.info('status=%s page_type=%s confidence=%s processing_ms=%s',
                output.get('status'), output.get('pageType'), output.get('confidence'), output.get('processingMs'))
    return _response(422 if output.get('status') == 'failure' else 200, output) if gateway else output
