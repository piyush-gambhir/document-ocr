"""Tests for the FastAPI server (deploy/docker/server.py).

Uses httpx AsyncClient with ASGI transport — does NOT require PaddleOCR.
"""

import io
import sys
import os

import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from httpx import AsyncClient, ASGITransport

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


class TestScan:
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

    async def test_scan_unsupported_page_returns_200(self, client, small_image):
        """Unsupported pages are classified, not treated as processing failures."""
        mock_dict = {
            "status": "unsupported_page",
            "documentType": "passport",
            "pageType": "passport_non_biodata",
            "confidence": 0.91,
            "fields": None,
            "mrzRaw": None,
            "mrzValid": False,
            "lowConfidence": False,
            "unsupportedReason": "NON_BIODATA_PAGE",
            "probeText": ["name of father", "address"],
            "errors": [],
            "warnings": ["NON_BIODATA_HINTS_2"],
            "processingMs": 90,
        }

        mock_result = MagicMock()
        mock_result.status = "unsupported_page"
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
        assert body["status"] == "unsupported_page"
        assert body["pageType"] == "passport_non_biodata"
        assert body["unsupportedReason"] == "NON_BIODATA_PAGE"
