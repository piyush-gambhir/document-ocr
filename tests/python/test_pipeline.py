"""Integration tests for the full pipeline using sample passport images."""

import os
from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).parent.parent.parent / "sample-passports"


def _has_samples() -> bool:
    return SAMPLE_DIR.exists() and any(SAMPLE_DIR.glob("*.jpg"))


@pytest.mark.skipif(not _has_samples(), reason="No sample passport images available")
class TestPipelineIntegration:
    """These tests require PaddleOCR to be installed and sample images present."""

    def test_scan_sample_1(self):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-1.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        result = scan(str(image_path))

        # Basic sanity checks
        assert result.processing_ms > 0
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

        # Should at least detect some text
        if result.success:
            assert result.fields.surname is not None or result.fields.passport_number is not None

    def test_scan_sample_2(self):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-2.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        result = scan(str(image_path))
        assert result.processing_ms > 0

    def test_scan_bytes(self):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-1.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        with open(image_path, "rb") as f:
            data = f.read()

        result = scan(data)
        assert result.processing_ms > 0
