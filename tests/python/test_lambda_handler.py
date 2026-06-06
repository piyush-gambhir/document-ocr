"""Tests for the AWS Lambda handler (deploy/lambda/handler.py).

`deploy/lambda` cannot be imported as a dotted module because `lambda` is a
Python keyword, so the handler module is loaded from its file path. The OCR
pipeline (`scan`) is stubbed — these tests cover request parsing, base64
decoding, response wrapping, and error mapping, not real OCR.
"""

import base64
import importlib.util
import json
from pathlib import Path

import pytest

_HANDLER_PATH = Path(__file__).resolve().parents[2] / "deploy" / "lambda" / "handler.py"


def _load_handler_module():
    spec = importlib.util.spec_from_file_location("lambda_handler_under_test", _HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_handler_module()


class _FakeResult:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class TestSuccess:
    def test_direct_invoke_returns_raw_result(self, mod, monkeypatch):
        payload = {"status": "success", "documentType": "passport", "pageType": "passport_biodata"}
        monkeypatch.setattr(mod, "scan", lambda data: _FakeResult(payload))

        result = mod.handler({"image_base64": _b64(b"fake-image-bytes")})

        assert result == payload
        assert "statusCode" not in result

    def test_failure_result_is_still_returned_raw(self, mod, monkeypatch):
        payload = {"status": "failure", "documentType": "passport", "errors": ["LOW_CONFIDENCE_EXTRACTION"]}
        monkeypatch.setattr(mod, "scan", lambda data: _FakeResult(payload))

        result = mod.handler({"image_base64": _b64(b"img")})

        assert result["status"] == "failure"

    def test_passes_decoded_bytes_to_scan(self, mod, monkeypatch):
        captured = {}

        def fake_scan(data):
            captured["data"] = data
            return _FakeResult({"status": "success"})

        monkeypatch.setattr(mod, "scan", fake_scan)
        mod.handler({"image_base64": _b64(b"\x89PNG\r\n")})

        assert captured["data"] == b"\x89PNG\r\n"

    def test_api_gateway_event_shape(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "scan", lambda data: _FakeResult({"status": "success"}))
        event = {"body": json.dumps({"image_base64": _b64(b"img")})}

        result = mod.handler(event)

        assert result["status"] == "success"


class TestInputErrors:
    def test_missing_image_returns_400(self, mod):
        resp = mod.handler({})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "MISSING_IMAGE"

    def test_invalid_base64_returns_400(self, mod):
        resp = mod.handler({"image_base64": "!!! not base64 !!!"})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "INVALID_BASE64"

    def test_file_too_large_returns_400(self, mod, monkeypatch):
        # Must not reach scan() — size is checked first.
        monkeypatch.setattr(mod, "scan", lambda data: pytest.fail("scan should not run"))
        big = _b64(b"\x00" * (10 * 1024 * 1024 + 1))
        resp = mod.handler({"image_base64": big})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "FILE_TOO_LARGE"


class TestPipelineErrors:
    def test_model_init_error_returns_503(self, mod, monkeypatch):
        from core.ocr_engine import OCRModelInitError

        def boom(data):
            raise OCRModelInitError("MODEL_INIT_FAILED: disk full")

        monkeypatch.setattr(mod, "scan", boom)
        resp = mod.handler({"image_base64": _b64(b"img")})
        assert resp["statusCode"] == 503
        assert json.loads(resp["body"])["error"] == "MODEL_INIT_FAILED"

    def test_image_quality_error_returns_400(self, mod, monkeypatch):
        from core.preprocessor import ImageQualityError

        def boom(data):
            raise ImageQualityError("IMAGE_TOO_BLURRY")

        monkeypatch.setattr(mod, "scan", boom)
        resp = mod.handler({"image_base64": _b64(b"img")})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "IMAGE_TOO_BLURRY"

    def test_unexpected_error_returns_500(self, mod, monkeypatch):
        def boom(data):
            raise ValueError("kaboom")

        monkeypatch.setattr(mod, "scan", boom)
        resp = mod.handler({"image_base64": _b64(b"img")})
        assert resp["statusCode"] == 500
        assert json.loads(resp["body"])["error"] == "INTERNAL_ERROR"
