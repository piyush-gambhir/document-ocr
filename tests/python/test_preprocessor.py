"""Tests for image preprocessing."""

import cv2
import numpy as np
import pytest

from core.preprocessor import (
    ImageQualityError,
    _check_resolution,
    _check_blur,
    _check_glare,
    _detect_document,
    _is_plausible_document_quad,
    _normalise,
    _order_points,
    preprocess,
)


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
        img = np.random.randint(0, 255, (800, 1200, 3), dtype=np.uint8)
        _check_blur(img)  # random noise = high variance, should pass

    def test_blurry_image(self):
        # Solid color image = zero Laplacian variance
        img = np.full((800, 1200, 3), 128, dtype=np.uint8)
        with pytest.raises(ImageQualityError, match="IMAGE_TOO_BLURRY"):
            _check_blur(img)


class TestGlareCheck:
    def test_no_glare(self):
        img = np.full((800, 1200, 3), 128, dtype=np.uint8)
        _check_glare(img)  # uniform mid-gray, no glare

    def test_heavy_glare(self):
        # Image mostly white (V channel > 250 for most pixels)
        img = np.full((800, 1200, 3), 255, dtype=np.uint8)
        result = _check_glare(img)
        assert result == "GLARE_DETECTED"


class TestNormalise:
    def test_output_width(self):
        # 900 < TARGET_WIDTH (1600), so no resize — width stays 900
        img = np.zeros((600, 900, 3), dtype=np.uint8)
        result = _normalise(img)
        assert result.shape[1] == 900

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

    def test_text_filled_image_without_real_boundary_keeps_full_resolution(self, tmp_path):
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
