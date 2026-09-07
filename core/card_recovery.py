"""Bounded pixel rereads for an identified, incomplete US passport-card front."""
from __future__ import annotations

import re

import cv2
import numpy as np

from .ocr_engine import TextRegion
from .structured_documents import extract_structured_document

_FIELD_LABELS = {
    'document_number': re.compile(r'^(?:passport\s*(?:card[\s\'’]*)?(?:number|no\.?)|card (?:number|no\.?))(?![A-Za-z])', re.I),
    'expiry_date': re.compile(r'^(?:card expires|expires(?: on)?|date of expiry|expiration date|expiry date|EXP)(?![A-Za-z])', re.I),
}


def _read_box(image, corners, width, height, reader) -> list[TextRegion]:
    corners = np.asarray(corners, np.float32)
    if (not 10 <= width <= 1600 or not 8 <= height <= 1200
            or corners.shape != (4, 2) or not np.isfinite(corners).all()):
        return []
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(corners, target)
    if abs(np.linalg.det(matrix)) < 1e-12:
        return []
    crop = cv2.warpPerspective(image, matrix, (width, height), borderValue=(255, 255, 255))
    inverse = np.linalg.inv(matrix)
    result = []
    for row in reader(crop):
        points = np.asarray(row.bbox, np.float32)
        if points.shape == (4, 2) and np.isfinite(points).all() and np.isfinite(row.confidence):
            original = cv2.perspectiveTransform(points[None], inverse)[0]
            result.append(TextRegion(row.text, original.round().astype(int).tolist(), row.confidence))
    return result


def _card_text_box(image, regions):
    """Follow a confident issuer heading and nearby text with the same angle."""
    headers = [row for row in regions if row.confidence >= .9 and len(row.bbox) == 4
               and re.fullmatch(r'UNITED STATES(?: OF AMERICA)?', row.text.strip(), re.I)]
    for header in sorted(headers, key=lambda row: len(row.text), reverse=True):
        points = np.asarray(header.bbox, np.float32)
        if not np.isfinite(points).all():
            continue
        origin = points[0]
        along = points[1] - origin
        width = np.linalg.norm(along)
        if width < 200:
            continue
        along /= width
        axes = np.array([along, [-along[1], along[0]]])
        cluster = []
        for row in regions:
            points = np.asarray(row.bbox, np.float32)
            if points.shape != (4, 2) or not np.isfinite(points).all():
                continue
            direction = points[1] - points[0]
            length = np.linalg.norm(direction)
            local = (points - origin) @ axes.T
            if (length > 0 and direction @ along / length >= .96
                    and local[:, 0].min() > -.15 * width and local[:, 0].max() < 1.2 * width
                    and local[:, 1].min() > -.08 * width and local[:, 1].max() < .85 * width):
                cluster.append(local)
        if len(cluster) < 5:
            continue
        points = np.vstack(cluster)
        left, top = points.min(axis=0) - [width * .07, width * .03]
        right, bottom = points.max(axis=0) + [width * .07, width * .05]
        crop_width, crop_height = int(right - left), int(bottom - top)
        h, w = image.shape[:2]
        if not (crop_width <= 1600 and crop_height <= 1200
                and 0 < crop_width * crop_height < w * h * .7):
            continue
        corners = np.array([[left, top], [right, top], [right, bottom], [left, bottom]]) @ axes + origin
        if (corners[:, 0].min() < 0 or corners[:, 1].min() < 0
                or corners[:, 0].max() >= w or corners[:, 1].max() >= h):
            continue
        return corners, crop_width, crop_height
    return None


def recover_card_fields(image, regions: list[TextRegion], ocr, recognize_line) -> list[TextRegion]:
    before = extract_structured_document(regions)
    if (before is None or before.document_type != 'passport_card' or before.issuing_country != 'US'
            or before.complete or before.errors or len(before.fields) < 3
            or not {'document_number', 'expiry_date'}.intersection(before.missing_required_fields)):
        return regions

    def acceptable(after):
        return bool(after and after.complete and after.issuing_country == before.issuing_country
                    and all(after.fields.get(key) == value for key, value in before.fields.items())
                    and all(after.field_evidence.get(key)
                            and min(item['confidence'] for item in after.field_evidence[key]) >= .9
                            for key in after.fields.keys() - before.fields.keys()))

    output = list(regions)
    if 'document_number' not in before.fields:
        # Locate an observed card-number label fragment. The fresh pixel read
        # must contain the exact label; its spelling is never patched in code.
        anchor = next((row for row in regions if row.confidence >= .9 and len(row.bbox) == 4
                       and re.fullmatch(r'.{1,24}\bcard\s+(?:number|no\.?)', row.text.strip(), re.I)
                       and not re.match(r'passport\s*card', row.text.strip(), re.I)), None)
        if anchor:
            points = np.asarray(anchor.bbox, np.float32)
            if np.isfinite(points).all():
                tl, tr, br, bl = points
                along = tr - tl
                width, height = int(np.linalg.norm(along)), int(np.linalg.norm(bl - tl))
                read = _read_box(image, [tl - .02 * along, tr + .02 * along,
                                         br + .02 * along, bl - .02 * along], width, height, recognize_line)
                if (len(read) == 1 and read[0].confidence >= .9
                        and re.fullmatch(r'passport\s*card\s+(?:number|no\.?)', read[0].text.strip(), re.I)):
                    output.extend(read)
    current = extract_structured_document(output)
    if current is None:
        return regions
    if current.complete:
        return output if acceptable(current) else regions
    geometry = _card_text_box(image, regions)
    if geometry is None:
        return regions
    reread = _read_box(image, *geometry, ocr)
    independently_read = extract_structured_document(reread)
    if independently_read is None or independently_read.document_type != before.document_type or independently_read.errors:
        return regions
    if any(key in independently_read.fields and independently_read.fields[key] != value
           for key, value in before.fields.items()):
        return regions
    # Keep unrelated reread text (especially large specimen watermarks) out of
    # existing field association. Admit only missing labels and their values.
    additions = []
    for key, label in _FIELD_LABELS.items():
        if key in current.fields or key not in independently_read.fields:
            continue
        evidence_boxes = [item['bbox'] for item in independently_read.field_evidence.get(key, [])]
        additions.extend(row for row in reread if row.confidence >= .9
                         and (label.match(row.text.strip()) or row.bbox in evidence_boxes))
    candidate = output + additions
    after = extract_structured_document(candidate)
    # Every newly admitted field must have high-confidence observed evidence.
    return candidate if acceptable(after) else regions
