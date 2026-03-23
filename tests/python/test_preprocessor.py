"""Tests for image preprocessing."""

import numpy as np
import pytest

from core.preprocessor import (
    ImageQualityError,
    _check_resolution,
    _check_blur,
    _check_glare,
    _normalise,
    _order_points,
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
