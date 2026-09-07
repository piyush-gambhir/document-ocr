"""Tests for the FastAPI server (deploy/docker/server.py).

Uses httpx AsyncClient with ASGI transport — does not load OCR models.
"""

import io
import asyncio
import threading

import pytest
from unittest.mock import patch, MagicMock

from httpx import AsyncClient, ASGITransport

from core.ocr_engine import OCRModelInitError
from deploy.docker.server import app
import deploy.docker.server as server_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_image():
    """A small valid JPEG image for upload tests."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="JPEG")
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
async def client():
    """Async httpx client bound to the FastAPI app (no startup events)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealth:
    async def test_health(self, client):
        """GET /health → 200, {"status": "ok"}."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestReady:
    async def test_ready_before_init(self, client):
        """GET /ready before models loaded → 503."""
        original = server_module._models_ready
        try:
            server_module._models_ready = False
            resp = await client.get("/ready")
            assert resp.status_code == 503
            assert resp.json()["status"] == "loading"
        finally:
            server_module._models_ready = original

    async def test_ready_after_init(self, client):
        """GET /ready after models loaded → 200."""
        original = server_module._models_ready
        try:
            server_module._models_ready = True
            resp = await client.get("/ready")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ready"
        finally:
            server_module._models_ready = original

    async def test_ready_reports_model_init_failure(self, client):
        """GET /ready when model init failed → 503 model_init_failed."""
        original_ready = server_module._models_ready
        original_err = server_module._model_init_error
        try:
            server_module._models_ready = False
            server_module._model_init_error = "MODEL_INIT_FAILED: ModelScope unreachable"
            resp = await client.get("/ready")
            assert resp.status_code == 503
            body = resp.json()
            assert body["status"] == "model_init_failed"
            assert "MODEL_INIT_FAILED" in body["error"]
        finally:
            server_module._models_ready = original_ready
            server_module._model_init_error = original_err

    async def test_lifespan_clears_a_transient_model_error(
        self,
        monkeypatch,
    ):
        original_ready = server_module._models_ready
        original_err = server_module._model_init_error
        try:
            monkeypatch.setattr(
                server_module,
                "_warm_up_ocr",
                MagicMock(
                    side_effect=OCRModelInitError("temporary model failure")
                ),
            )
            async with server_module._lifespan(app):
                assert server_module._models_ready is False
                assert "temporary model failure" in (
                    server_module._model_init_error or ""
                )

            monkeypatch.setattr(
                server_module,
                "_warm_up_ocr",
                MagicMock(return_value=None),
            )
            async with server_module._lifespan(app):
                assert server_module._models_ready is True
                assert server_module._model_init_error is None
        finally:
            server_module._models_ready = original_ready
            server_module._model_init_error = original_err


def test_warm_up_initializes_configured_kyc_models(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "core.kyc_ocr.configured_kyc_languages",
        lambda: ("en", "devanagari", "ta"),
    )
    monkeypatch.setattr(
        "core.ocr_engine._get_ocr",
        lambda language: calls.append(language),
    )

    server_module._warm_up_ocr()

    assert calls == ["en", "devanagari", "ta"]


class TestScan:
    async def test_scan_requires_configured_bearer_token(self, client, small_image):
        with patch.object(server_module, "API_TOKEN", "test-token"):
            unauthorized = await client.post(
                "/scan",
                files={"image": ("passport.jpg", small_image, "image/jpeg")},
            )
            assert unauthorized.status_code == 401
            assert unauthorized.json()["detail"] == "UNAUTHORIZED"

            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.page_type = "passport_biodata"
            mock_result.confidence = 0.9
            mock_result.processing_ms = 10
            mock_result.errors = []
            mock_result.to_dict.return_value = {"status": "success"}

            with patch("deploy.docker.server.scan", return_value=mock_result):
                authorized = await client.post(
                    "/scan",
                    headers={"Authorization": "Bearer test-token"},
                    files={"image": ("passport.jpg", small_image, "image/jpeg")},
                )
            assert authorized.status_code == 200

    async def test_scan_invalid_content_type(self, client):
        """Upload text/plain → 400 INVALID_CONTENT_TYPE."""
        resp = await client.post(
            "/scan",
            files={"image": ("test.txt", b"not an image", "text/plain")},
        )
        assert resp.status_code == 400
        assert "INVALID_CONTENT_TYPE" in resp.text

    async def test_scan_empty_file(self, client):
        """Upload empty image/jpeg → 400 EMPTY_FILE."""
        resp = await client.post(
            "/scan",
            files={"image": ("empty.jpg", b"", "image/jpeg")},
        )
        assert resp.status_code == 400
        assert "EMPTY_FILE" in resp.text

    async def test_scan_file_too_large(self, client):
        """Upload >10MB image/jpeg → 400 FILE_TOO_LARGE."""
        big_data = b"\x00" * (10 * 1024 * 1024 + 1)
        resp = await client.post(
            "/scan",
            files={"image": ("big.jpg", big_data, "image/jpeg")},
        )
        assert resp.status_code == 400
        assert "FILE_TOO_LARGE" in resp.text

    async def test_scan_success_camel_case(self, client, small_image):
        """Successful scan returns camelCase keys from .to_dict()."""
        mock_dict = {
            "status": "success",
            "documentType": "passport",
            "pageType": "passport_biodata",
            "confidence": 0.85,
            "fields": {
                "surname": "KUMAR",
                "givenNames": "RAJ",
                "fullName": "RAJ KUMAR",
                "passportNumber": "J1234567",
                "nationality": "IND",
                "dateOfBirth": "1990-05-20",
                "sex": "M",
                "expiryDate": "2030-05-20",
                "countryCode": "IND",
            },
            "mrzRaw": None,
            "mrzValid": True,
            "lowConfidence": False,
            "unsupportedReason": None,
            "probeText": ["passport"],
            "errors": [],
            "warnings": [],
            "processingMs": 150,
        }

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.page_type = "passport_biodata"
        mock_result.confidence = 0.85
        mock_result.processing_ms = 150
        mock_result.errors = []
        mock_result.to_dict.return_value = mock_dict

        with patch("deploy.docker.server.scan", return_value=mock_result):
            resp = await client.post(
                "/scan",
                files={"image": ("passport.jpg", small_image, "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["documentType"] == "passport"
        assert body["pageType"] == "passport_biodata"
        assert body["confidence"] == 0.85
        assert body["fields"]["surname"] == "KUMAR"
        assert body["fields"]["givenNames"] == "RAJ"

    async def test_scan_non_biodata_returns_200_with_back_fields(self, client, small_image):
        """Non-biodata pages return success with back page fields extracted."""
        mock_dict = {
            "status": "success",
            "documentType": "passport",
            "pageType": "passport_non_biodata",
            "confidence": 0.91,
            "fields": None,
            "backPageFields": {
                "fatherName": "JOHN DOE SR",
                "motherName": "JANE DOE",
                "spouseName": None,
                "address": "123 MAIN ST",
                "pincode": "500020",
                "city": "HYDERABAD",
                "state": "Telangana",
                "fileNumber": None,
                "oldPassportNumber": None,
                "oldPassportDateOfIssue": None,
                "oldPassportPlaceOfIssue": None,
            },
            "mrzRaw": None,
            "mrzValid": False,
            "lowConfidence": False,
            "unsupportedReason": None,
            "probeText": ["name of father", "address"],
            "errors": [],
            "warnings": ["NON_BIODATA_HINTS_2"],
            "processingMs": 90,
        }

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.page_type = "passport_non_biodata"
        mock_result.confidence = 0.91
        mock_result.processing_ms = 90
        mock_result.errors = []
        mock_result.to_dict.return_value = mock_dict

        with patch("deploy.docker.server.scan", return_value=mock_result):
            resp = await client.post(
                "/scan",
                files={"image": ("passport.jpg", small_image, "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["pageType"] == "passport_non_biodata"
        assert body["backPageFields"] is not None
        assert body["backPageFields"]["fatherName"] == "JOHN DOE SR"

    async def test_scan_model_init_error_returns_503(self, client, small_image):
        """If OCR models fail to initialise mid-request → 503 MODEL_INIT_FAILED."""
        def boom(*args, **kwargs):
            raise OCRModelInitError("MODEL_INIT_FAILED: disk full")

        with patch("deploy.docker.server.scan", side_effect=boom):
            resp = await client.post(
                "/scan",
                files={"image": ("passport.jpg", small_image, "image/jpeg")},
            )

        assert resp.status_code == 503
        assert resp.json()["error"] == "MODEL_INIT_FAILED"


async def test_timeout_retains_ocr_slot_until_worker_exits(client, small_image, monkeypatch):
    from core.pipeline import DocumentScanResult

    release_first = threading.Event()
    second_started = threading.Event()
    calls = []

    def slow_scan(data):
        calls.append(data)
        if len(calls) == 1:
            release_first.wait(timeout=2)
        else:
            second_started.set()
        return DocumentScanResult('success', 'passport', 'passport_biodata', 0.9)

    monkeypatch.setattr(server_module, '_ocr_semaphore', asyncio.Semaphore(1))
    monkeypatch.setattr(server_module, 'SCAN_TIMEOUT_SECONDS', 0.05)
    monkeypatch.setattr(server_module, 'scan', slow_scan)
    files = {'image': ('synthetic.jpg', small_image, 'image/jpeg')}
    second = None
    try:
        first = await client.post('/scan', files=files)
        assert first.status_code == 504
        assert first.json() == {'error': 'SCAN_TIMEOUT'}
        assert server_module._ocr_semaphore.locked()
        second = asyncio.create_task(client.post('/scan', files=files))
        await asyncio.sleep(0.02)
        assert not second_started.is_set()
        release_first.set()
        response = await asyncio.wait_for(second, timeout=1)
        assert response.status_code == 200
        assert second_started.is_set()
    finally:
        release_first.set()
        if second is not None:
            await second
