"""Burn caller-reviewed redaction polygons into a metadata-free PNG raster."""
import json
import math

import cv2
import numpy as np

from .pipeline import preview_image


def render_preview(data: bytes) -> bytes:
    return _png(preview_image(data))


def redact(data: bytes, boxes: str | list) -> bytes:
    if isinstance(boxes, str):
        try:
            boxes = json.loads(boxes)
        except ValueError as exc:
            raise ValueError('INVALID_REDACTION_BOXES') from exc
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= 200:
        raise ValueError('INVALID_REDACTION_BOXES')
    image = preview_image(data).copy()
    height, width = image.shape[:2]
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError('INVALID_REDACTION_BOXES')
        for point in box:
            if (not isinstance(point, list) or len(point) != 2
                or any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in point)
                or not (0 <= point[0] <= width and 0 <= point[1] <= height)):
                raise ValueError('INVALID_REDACTION_BOXES')
        points = np.array(box, dtype=np.int32)
        if abs(cv2.contourArea(points)) < 1:
            raise ValueError('INVALID_REDACTION_BOXES')
        # Bounding rectangles intentionally cover the entire text quad with a
        # small ink margin. PNG output has no retained PDF text layer or EXIF.
        x0, y0 = np.maximum(points.min(axis=0) - 3, 0)
        x1, y1 = np.minimum(points.max(axis=0) + 4, (width, height))
        image[y0:y1, x0:x1] = 0
    return _png(image)


def _png(image) -> bytes:
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('IMAGE_ENCODING_FAILED')
    return encoded.tobytes()
