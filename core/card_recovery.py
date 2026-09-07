"""Bounded pixel rereads for an identified, incomplete US passport-card front."""
from __future__ import annotations

import re

import cv2
import numpy as np

from .ocr_engine import TextRegion
from .structured_documents import _us_date, extract_structured_document

_FIELD_LABELS = {
    'document_number': re.compile(r'^(?:passport\s*(?:card[\s\'’]*)?(?:number|no\.?)|card (?:number|no\.?))(?![A-Za-z])', re.I),
    'expiry_date': re.compile(r'^(?:card expires|expires(?:\s*on)?|date of expiry|expiration date|expiry date|EXP)(?![A-Za-z])', re.I),
}

_TRUNCATED_DATE = re.compile(r'(?:\d{1,2}\s*[A-Za-z]{3,9}\s*\d{1,3}|\d{1,2}[-/]\d{1,2}[-/]\d{1,3})')


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


def _expiry_date_region(regions):
    """Select one truncated date directly below one confident expiry label."""
    labels = [row for row in regions if row.confidence >= .9
              and _FIELD_LABELS['expiry_date'].fullmatch(row.text.strip())]
    if len(labels) != 1:
        return None
    label = np.asarray(labels[0].bbox, np.float32)
    if label.shape != (4, 2) or not np.isfinite(label).all():
        return None
    along = label[1] - label[0]
    width = np.linalg.norm(along)
    if width < 20:
        return None
    along /= width
    axes = np.array([along, [-along[1], along[0]]])
    local_label = (label - label[0]) @ axes.T
    height = np.ptp(local_label[:, 1])
    if height < 8:
        return None
    candidates = []
    for row in regions:
        if not _TRUNCATED_DATE.fullmatch(row.text.strip()) or _us_date(row.text) is not None:
            continue
        points = np.asarray(row.bbox, np.float32)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        direction = points[1] - points[0]
        length = np.linalg.norm(direction)
        local = (points - label[0]) @ axes.T
        left, top = local.min(axis=0)
        right, bottom = local.max(axis=0)
        # Compare the top-edge centers. Taking the extreme corner exaggerates
        # overlap when a long date and its short label have slightly different
        # detected angles despite sharing the same printed baseline.
        gap = local[:2, 1].mean() - local_label[:, 1].max()
        if (length > 0 and direction @ along / length >= .98
                and abs(left) <= max(20, height * 2)
                and -.25 * height <= gap <= 2.5 * height
                and .65 * height <= bottom - top <= 2.5 * height
                and 0 < right - left <= width * 3):
            candidates.append(row)
    return candidates[0] if len(candidates) == 1 else None


def _read_expiry_date(image, regions, recognize_line, unenhanced_image=None):
    """At most two direct reads, with agreement required for denoise recovery."""
    anchor = _expiry_date_region(regions)
    if anchor is None:
        return []
    tl, tr, br, bl = np.asarray(anchor.bbox, np.float32)
    along = tr - tl
    corners = np.array([tl - .05 * along, tr + .05 * along,
                        br + .05 * along, bl - .05 * along])
    h, w = image.shape[:2]
    if (corners[:, 0].min() < 0 or corners[:, 1].min() < 0
            or corners[:, 0].max() >= w or corners[:, 1].max() >= h):
        return []
    width, height = int(np.linalg.norm(along) * 1.1), int(np.linalg.norm(bl - tl))
    prefix = re.sub(r'[\s/-]', '', anchor.text).upper()

    def valid(read):
        # Preserve all characters already observed in the truncated date. The
        # missing suffix must come from pixels and parse as a complete date.
        return (len(read) == 1 and _us_date(read[0].text) is not None
                and re.sub(r'[\s/-]', '', read[0].text).upper().startswith(prefix))

    direct = _read_box(image, corners, width, height, recognize_line)
    if not valid(direct):
        # A security background can obscure the final digit after CLAHE. Keep
        # the exact observed prefix, and reread the same coordinates once in
        # the original-color plane. Never run both this and denoise recovery.
        if (len(direct) == 1 and direct[0].confidence >= .9
                and re.sub(r'[\s/-]', '', direct[0].text).upper() == prefix
                and unenhanced_image is not None and unenhanced_image is not image
                and unenhanced_image.shape == image.shape):
            original = _read_box(unenhanced_image, corners, width, height, recognize_line)
            if valid(original) and original[0].confidence >= .9:
                return original
        return []
    if direct[0].confidence >= .9:
        return direct
    if direct[0].confidence < .8:
        return []
    denoised = _read_box(image, corners, width, height,
                         lambda crop: recognize_line(cv2.medianBlur(crop, 3)))
    if (valid(denoised) and denoised[0].confidence >= .9
            and _us_date(denoised[0].text) == _us_date(direct[0].text)):
        return denoised
    return []


def recover_card_fields(image, regions: list[TextRegion], ocr, recognize_line, *,
                        unenhanced_image=None) -> list[TextRegion]:
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
    if before.missing_required_fields == ['expiry_date']:
        # No detector rerun: one observed date box, at most two direct reads.
        # Cards missing other fields keep the existing number/cluster budget.
        date_read = _read_expiry_date(image, regions, recognize_line, unenhanced_image)
        if date_read:
            candidate = output + date_read
            if acceptable(extract_structured_document(candidate)):
                return candidate
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
