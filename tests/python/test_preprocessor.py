"""Tests for image preprocessing."""

import io
import json
import subprocess
import sys

import cv2
import numpy as np
import pytest
from PIL import Image

from core.preprocessor import (
    ImageQualityError,
    _check_resolution,
    _check_blur,
    _check_glare,
    _detect_document,
    _is_plausible_document_quad,
    _load_image,
    _normalise,
    _order_points,
    preprocess,
)


class TestPdfLoading:
    @staticmethod
    def _pdf_bytes() -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (800, 600), "white").save(
            output,
            format="PDF",
            resolution=150,
        )
        return output.getvalue()

    def test_loads_pdf_path(self, tmp_path):
        path = tmp_path / "document.pdf"
        path.write_bytes(self._pdf_bytes())

        image = _load_image(path)

        assert image.ndim == 3
        assert image.shape[2] == 3
        assert min(image.shape[:2]) >= 600

    def test_loads_pdf_bytes(self):
        image = _load_image(self._pdf_bytes())

        assert image.ndim == 3
        assert image.shape[2] == 3
        assert min(image.shape[:2]) >= 600


class TestResolutionCheck:
    def test_valid_resolution(self):
        img = np.zeros((800, 1200, 3), dtype=np.uint8)
        _check_resolution(img)  # should not raise

    def test_too_small(self):
        img = np.zeros((400, 300, 3), dtype=np.uint8)
        with pytest.raises(ImageQualityError, match="RESOLUTION_TOO_LOW"):
            _check_resolution(img)

    def test_boundary(self):
        img = np.zeros((600, 800, 3), dtype=np.uint8)
        _check_resolution(img)  # exactly at minimum, should pass


class TestBlurCheck:
    def test_sharp_image(self):
        # Create image with high-frequency content (not blurry)
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        cv2.putText(img, "DOCUMENT OCR", (60, 400), cv2.FONT_HERSHEY_SIMPLEX,
                    3, (0, 0, 0), 5)
        _check_blur(img)  # readable, sharp text should pass

    def test_blurry_image(self):
        # Solid color image = zero Laplacian variance
        img = np.full((800, 1200, 3), 128, dtype=np.uint8)
        with pytest.raises(ImageQualityError, match="IMAGE_TOO_BLURRY"):
            _check_blur(img)


class TestGlareCheck:
    def test_no_glare(self):
        img = np.full((800, 1200, 3), 128, dtype=np.uint8)
        assert _check_glare(img) is None

    def test_heavy_glare(self):
        # Image mostly white (V channel > 250 for most pixels)
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        result = _check_glare(img)
        assert result == "GLARE_DETECTED"


class TestNormalise:
    def test_preserves_aspect_ratio(self):
        # 900 < TARGET_WIDTH (1600), so no resize — dimensions unchanged
        img = np.zeros((600, 900, 3), dtype=np.uint8)
        result = _normalise(img)
        assert result.shape[0] == 600
        assert result.shape[1] == 900

    def test_downscale_large_image(self):
        # 2400 > TARGET_WIDTH (1600), so it should downscale
        img = np.zeros((1200, 2400, 3), dtype=np.uint8)
        result = _normalise(img)
        assert result.shape[1] == 1600
        expected_h = int(1200 * (1600 / 2400))
        assert result.shape[0] == expected_h


class TestOrderPoints:
    def test_already_ordered(self):
        pts = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float32)
        ordered = _order_points(pts)
        np.testing.assert_array_equal(ordered[0], [0, 0])     # top-left
        np.testing.assert_array_equal(ordered[1], [100, 0])    # top-right
        np.testing.assert_array_equal(ordered[2], [100, 100])  # bottom-right
        np.testing.assert_array_equal(ordered[3], [0, 100])    # bottom-left


class TestDocumentQuadPlausibility:
    img_area = 1000.0 * 800.0  # arbitrary reference frame

    def test_full_frame_quad_accepted(self):
        quad = np.array([[[0, 0]], [[1000, 0]], [[1000, 800]], [[0, 800]]], dtype=np.int32)
        assert _is_plausible_document_quad(quad, self.img_area)

    def test_tiny_quad_rejected(self):
        # The exact failure mode from the user's image: ~0.1% of the frame.
        quad = np.array(
            [[[18, 24]], [[30, 95]], [[26, 22]], [[1009, 63]]],
            dtype=np.int32,
        )
        assert not _is_plausible_document_quad(quad, self.img_area)

    def test_non_convex_quad_rejected(self):
        # A self-intersecting "bowtie" quad — clearly not a document.
        quad = np.array(
            [[[0, 0]], [[1000, 800]], [[1000, 0]], [[0, 800]]], dtype=np.int32,
        )
        assert not _is_plausible_document_quad(quad, self.img_area)

    def test_thin_strip_rejected_by_aspect(self):
        # Covers > 30 % of area but is a 10:1 strip — not a passport shape.
        quad = np.array(
            [[[0, 0]], [[1000, 0]], [[1000, 80]], [[0, 80]]], dtype=np.int32,
        )
        assert not _is_plausible_document_quad(quad, self.img_area)


class TestDocumentDetection:
    def test_no_real_boundary_returns_none(self):
        # Pure white image — no edges, no contours, no quad.
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        corners, warnings = _detect_document(img)
        assert corners is None
        assert "NO_DOCUMENT_BOUNDARY_DETECTED" in warnings

    def test_noise_contour_does_not_yield_bogus_quad(self):
        # White background with a tiny black square (~1 % of frame).
        # Without the plausibility check, polygon approximation of this
        # contour would be returned as the "document" and silently destroy
        # the image during perspective correction.
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (40, 40), (140, 140), (0, 0, 0), -1)
        corners, warnings = _detect_document(img)
        assert corners is None
        assert "NO_DOCUMENT_BOUNDARY_DETECTED" in warnings

    def test_full_document_boundary_detected(self):
        # Light grey "document" rectangle on a black background.
        img = np.zeros((800, 1200, 3), dtype=np.uint8)
        cv2.rectangle(img, (60, 60), (1140, 740), (220, 220, 220), -1)
        corners, _ = _detect_document(img)
        assert corners is not None
        # All four corners should land inside the document footprint.
        for x, y in corners.tolist():
            assert 50 <= x <= 1150
            assert 50 <= y <= 750


class TestPreprocessFallbackToRaw:
    """Defense-in-depth: even if a bogus quad slips through detection, the
    perspective-correction output validation must reject it and use the raw
    image so downstream OCR still has something to work with."""

    def _encode(self, img):
        ok, buf = cv2.imencode(".png", img)
        assert ok
        return buf.tobytes()

    def test_text_filled_image_without_real_boundary_keeps_full_resolution(self):
        # Synthetic page with text but no document edges — mimics a flat scan
        # that fills the frame. Preprocessing should not collapse it into a
        # tiny strip.
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        cv2.putText(img, "PASSPORT", (200, 200), cv2.FONT_HERSHEY_SIMPLEX,
                    3, (0, 0, 0), 6)
        cv2.putText(img, "Republic of Testland", (200, 350),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
        cv2.putText(img, "Name of Father", (200, 500),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (60, 60, 60), 2)
        cv2.putText(img, "JOHN DOE", (200, 560),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)

        result = preprocess(self._encode(img))
        # Output width should still be the original (no downscale at < 1600).
        assert result.image.shape[1] == 1200
        # And height should be roughly preserved — emphatically not a sliver.
        assert result.image.shape[0] >= 700


class TestImageDecoding:
    @pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
    def test_exif_orientation_is_identical_for_path_and_upload(self, tmp_path, orientation):
        # Asymmetric color blocks catch mirrored and rotated decoding mistakes.
        pixels = np.zeros((80, 120, 3), dtype=np.uint8)
        pixels[:40, :60] = (230, 20, 40)
        pixels[40:, 60:] = (10, 170, 90)
        photo = Image.fromarray(pixels)
        exif = Image.Exif()
        exif[274] = orientation
        output = io.BytesIO()
        photo.save(output, format="JPEG", exif=exif)
        data = output.getvalue()
        path = tmp_path / "photo.jpg"
        path.write_bytes(data)
        operations = {
            2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
            4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
            6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
            8: Image.Transpose.ROTATE_90,
        }
        with Image.open(io.BytesIO(data)) as decoded:
            expected = cv2.cvtColor(
                np.array(decoded.transpose(operations[orientation]).convert("RGB")),
                cv2.COLOR_RGB2BGR,
            )
        np.testing.assert_array_equal(_load_image(data), expected)
        np.testing.assert_array_equal(_load_image(path), expected)

    @pytest.mark.parametrize("extension", [".heic", ".heif"])
    def test_heif_upload_matches_path(self, tmp_path, extension):
        import pillow_heif

        pillow_heif.register_heif_opener()
        photo = Image.new("RGB", (120, 80), (220, 30, 40))
        output = io.BytesIO()
        photo.save(output, format="HEIF")
        data = output.getvalue()
        path = tmp_path / ("photo" + extension)
        path.write_bytes(data)
        uploaded = _load_image(data)
        assert uploaded.shape == (80, 120, 3)
        np.testing.assert_array_equal(uploaded, _load_image(path))
        np.testing.assert_allclose(uploaded[20, 20], (40, 30, 220), atol=5)

    @pytest.mark.parametrize("data,error", [
        (b"", "INVALID_IMAGE"),
        (b"not an image", "INVALID_IMAGE"),
        (b"%PDF-invalid", "INVALID_PDF"),
    ])
    def test_corrupt_upload_has_a_clear_input_error(self, data, error):
        with pytest.raises(ImageQualityError, match=error):
            _load_image(data)


def test_rotated_quad_never_reuses_a_corner():
    from itertools import permutations
    from core.preprocessor import _perspective_correct

    diamond = np.array([[300, 0], [600, 300], [300, 600], [0, 300]], dtype=np.float32)
    for points in permutations(diamond):
        ordered = _order_points(np.array(points))
        np.testing.assert_array_equal(ordered, diamond)
    image = np.full((601, 601, 3), 220, dtype=np.uint8)
    cv2.putText(image, "TEXT", (150, 320), cv2.FONT_HERSHEY_SIMPLEX,
                2, (0, 0, 0), 4)
    corrected = _perspective_correct(image, diamond)
    assert corrected.shape[:2] == (424, 424)
    assert corrected.mean() > 200
    assert corrected.min() < 20  # the text survived the transform


def test_first_heif_upload_in_a_fresh_process():
    import pillow_heif

    output = io.BytesIO()
    picture = Image.new("RGB", (120, 80), (220, 30, 40))
    pillow_heif.from_bytes("RGB", picture.size, picture.tobytes()).save(output)
    process = subprocess.run(
        [sys.executable, "-c", (
            "import json, sys; from core.preprocessor import _load_image; "
            "image = _load_image(sys.stdin.buffer.read()); "
            "print(json.dumps({'shape': image.shape, 'pixel': image[20,20].tolist()}))"
        )],
        input=output.getvalue(), capture_output=True, check=True,
    )
    result = json.loads(process.stdout)
    assert result['shape'] == [80, 120, 3]
    np.testing.assert_allclose(result['pixel'], (40, 30, 220), atol=5)


@pytest.mark.parametrize("format", ["PNG", "TIFF"])
def test_16_bit_scan_preserves_tonal_range(format):
    levels = np.array([[0, 4096, 8192, 32768, 49152, 65535]], dtype=np.uint16)
    output = io.BytesIO()
    Image.fromarray(levels).save(output, format=format)
    decoded = _load_image(output.getvalue())
    expected = np.repeat(np.array([[[0], [16], [32], [128], [192], [255]]], dtype=np.uint8), 3, axis=2)
    np.testing.assert_array_equal(decoded, expected)
