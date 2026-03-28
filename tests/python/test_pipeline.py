"""Integration tests for the full pipeline using sample passport images."""

import json
from pathlib import Path

import cv2
import pytest

SAMPLE_DIR = Path(__file__).parent.parent.parent / "sample-passports"
MANIFEST_PATH = SAMPLE_DIR / "manifest.json"


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
        manifest = json.loads(MANIFEST_PATH.read_text())
        expected = manifest["sample-indian-passport-1.jpg"]

        assert result.processing_ms > 0
        assert result.status == expected["status"]
        assert result.document_type == expected["documentType"]
        assert result.page_type == expected["pageType"]
        assert result.mrz_valid is True
        assert result.fields is not None
        assert result.fields.surname == expected["fields"]["surname"]
        assert result.fields.given_names == expected["fields"]["givenNames"]
        assert result.fields.full_name == expected["fields"]["fullName"]
        assert result.fields.passport_number == expected["fields"]["passportNumber"]
        assert result.fields.nationality == expected["fields"]["nationality"]
        assert result.fields.date_of_birth == expected["fields"]["dateOfBirth"]
        assert result.fields.sex == expected["fields"]["sex"]
        assert result.fields.expiry_date == expected["fields"]["expiryDate"]
        assert result.fields.issue_date == expected["fields"]["issueDate"]
        assert result.fields.place_of_birth == expected["fields"]["placeOfBirth"]
        assert result.fields.country_code == expected["fields"]["countryCode"]
        assert list(result.mrz_raw) == expected["mrzRaw"]

    def test_scan_sample_2(self):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-2.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        result = scan(str(image_path))
        manifest = json.loads(MANIFEST_PATH.read_text())
        expected = manifest["sample-indian-passport-2.jpg"]
        assert result.processing_ms > 0
        assert result.status == expected["status"]
        assert result.document_type == expected["documentType"]
        assert result.page_type == expected["pageType"]
        assert result.unsupported_reason == expected["unsupportedReason"]

    def test_scan_bytes(self):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-1.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        with open(image_path, "rb") as f:
            data = f.read()

        result = scan(data)
        assert result.processing_ms > 0
        assert result.status == "success"

    @pytest.mark.parametrize(
        ("variant_name", "transform"),
        [
            (
                "rotated_3deg",
                lambda image: cv2.warpAffine(
                    image,
                    cv2.getRotationMatrix2D((image.shape[1] / 2, image.shape[0] / 2), 3.0, 1.0),
                    (image.shape[1], image.shape[0]),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE,
                ),
            ),
            ("blurred_3x3", lambda image: cv2.GaussianBlur(image, (3, 3), 0)),
            ("low_light", lambda image: cv2.convertScaleAbs(image, alpha=0.72, beta=-25)),
            (
                "glare",
                lambda image: _apply_glare(image),
            ),
        ],
    )
    def test_scan_augmented_front_page_variants(self, variant_name, transform):
        from core.pipeline import scan

        image_path = SAMPLE_DIR / "sample-indian-passport-1.jpg"
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")

        image = cv2.imread(str(image_path))
        assert image is not None, f"Could not read sample image: {image_path}"

        variant = transform(image)
        ok, encoded = cv2.imencode(".jpg", variant, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        assert ok, f"Could not encode variant: {variant_name}"

        result = scan(encoded.tobytes())
        assert result.status == "success"
        assert result.page_type == "passport_biodata"
        assert result.mrz_valid is True
        assert result.fields is not None
        assert result.fields.passport_number == "J8369854"
        assert result.fields.surname == "RAMADUGULA"


def _apply_glare(image):
    overlay = image.copy()
    height, width = image.shape[:2]
    cv2.ellipse(
        overlay,
        (int(width * 0.58), int(height * 0.48)),
        (140, 70),
        -15,
        0,
        360,
        (255, 255, 255),
        -1,
    )
    return cv2.addWeighted(overlay, 0.22, image, 0.78, 0)
