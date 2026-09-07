"""Bounded pixel rereads for unchecked TD3/MRV issuer and nationality fields.

Checksums do not protect those fields. Two differently cropped recognizer
reads must agree before replacing an implausible code; an already plausible,
complete MRZ has no additional inference cost. This is recognition recovery,
not document authentication or a way to infer nationality from the issuer.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .document_registry import is_known_mrz_country
from .mrz_parser import _clean_mrz_text, parse_mrz, verify_check_digit
from .ocr_engine import TextRegion
from .travel_mrz import parse_travel_mrz


def _geometry(region):
    points = np.asarray(region.bbox, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        return None
    u, v = points[1] - points[0], points[3] - points[0]
    width, height = np.linalg.norm(u), np.linalg.norm(v)
    if width < 150 or height < 8 or width < height * 5:
        return None
    if abs(float(np.linalg.det(np.stack([u, v])))) < width * height * .5:
        return None
    return points, u, v, width, height


def _pairs(regions):
    pairs = []
    for header in regions:
        first = _clean_mrz_text(header.text)
        shape = _geometry(header)
        if (shape is None or not 28 <= len(first) <= 44
                or not re.match(r"[PV][A-Z<]", first)
                or first.count("<") < 3 or "<<" not in first):
            continue
        points, u, v, width, height = shape
        for body in regions:
            second = _clean_mrz_text(body.text)
            body_shape = _geometry(body)
            if body is header or body_shape is None or not 28 <= len(second) <= 44:
                continue
            if sum(character.isdigit() for character in second) < 10:
                continue
            delta = body_shape[0].mean(axis=0) - points.mean(axis=0)
            across = abs(float(np.dot(delta, u) / width))
            below = float(np.dot(delta, v) / height)
            if across < width * .2 and height * .6 < below < height * 3:
                pairs.append((header, body))
    return pairs


def _checked(first, second, header, body):
    """Return parsed checked fields only for complete, calendar-valid pairs."""
    width = 44 if first.startswith("P") else len(first)
    if width not in (36, 44) or len(first) != width or len(second) != width:
        return None
    candidate = [TextRegion(first, header.bbox, header.confidence),
                 TextRegion(second, body.bbox, body.confidence)]
    if first.startswith("P"):
        parsed = parse_mrz(candidate)
        if not parsed or not parsed.overall_checksum_valid or parsed.errors:
            return None
        fields = tuple(getattr(parsed, name).value for name in
                       ("passport_number", "date_of_birth", "expiry_date", "sex"))
        fields += (parsed.personal_number.raw,)
    else:
        parsed = parse_travel_mrz(candidate)
        if not parsed or not parsed.checks.get("mrz_checksums_valid"):
            return None
        if any(error not in ("UNKNOWN_ISSUING_COUNTRY", "UNKNOWN_NATIONALITY") for error in parsed.errors):
            return None
        fields = tuple(parsed.fields.get(name) for name in
                       ("document_number", "date_of_birth", "expiry_date", "sex"))
    return fields if all(fields) else None


def _preserves_checked_body(original, candidate):
    # Protect each previously verified field even when the original pair was
    # incomplete and no complete MRZ result could be parsed.
    for start, stop, check in ((0, 9, 9), (13, 19, 19), (21, 27, 27), (28, 42, 42)):
        if len(original) > check and verify_check_digit(original[start:stop], original[check]):
            if original[start:stop] != candidate[start:stop]:
                return False
    if len(original) > 20 and original[20] in "MFX<" and original[20] != candidate[20]:
        return False
    return True


def _read_line(image, region, reader, horizontal_margin, vertical_margin):
    shape = _geometry(region)
    if shape is None:
        return None
    points, u, v, width, height = shape
    tl, tr, br, bl = points
    source = np.float32([tl - u * horizontal_margin - v * vertical_margin,
                         tr + u * horizontal_margin - v * vertical_margin,
                         br + u * horizontal_margin + v * vertical_margin,
                         bl - u * horizontal_margin + v * vertical_margin])
    width = round(width * (1 + 2 * horizontal_margin))
    height = round(height * (1 + 2 * vertical_margin))
    if width > image.shape[1] * 2 or height > image.shape[0] * .25:
        return None
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    transform = cv2.getPerspectiveTransform(source, target)
    if not np.isfinite(transform).all() or abs(float(np.linalg.det(transform))) < 1e-12:
        return None
    crop = cv2.warpPerspective(image, transform, (width, height), borderValue=(255, 255, 255))
    reads = reader(crop)
    if len(reads) != 1 or reads[0].confidence < .80:
        return None
    read = reads[0]
    text = _clean_mrz_text(read.text)
    if len(text) not in (36, 44) or not re.fullmatch(r"[A-Z0-9<]+", text):
        return None
    box = np.asarray(read.bbox, np.float32)
    if box.shape != (4, 2) or not np.isfinite(box).all():
        return None
    mapped = cv2.perspectiveTransform(box[None], np.linalg.inv(transform))[0]
    if not np.isfinite(mapped).all():
        return None
    return TextRegion(text, mapped.round().astype(int).tolist(), read.confidence)


def recover_travel_mrz(image, regions: list[TextRegion], recognize_line) -> list[TextRegion]:
    """Reread at most one ambiguous pair, with two recognitions per bad row.

    No document hint or expected value is used. Disagreeing rereads, changed
    checked fields, and changes between plausible country codes are rejected.
    Multiple candidate documents are left to the normal rejection path.
    """
    pairs = _pairs(regions)
    if len(pairs) != 1:
        return regions
    header, body = pairs[0]
    first, second = _clean_mrz_text(header.text), _clean_mrz_text(body.text)
    existing = _checked(first, second, header, body)
    plausible = is_known_mrz_country(first[2:5]) and is_known_mrz_country(second[10:13])
    if existing and plausible:
        return regions
    first_ok = bool(len(first) in ((44,) if first.startswith("P") else (36, 44))
                    and re.fullmatch(r"[PV][A-Z<][A-Z<]{3}[A-Z<]+", first)
                    and is_known_mrz_country(first[2:5]))
    second_ok = bool(existing and is_known_mrz_country(second[10:13]))
    # A malformed header alone does not invalidate an otherwise complete,
    # checked body. Preserve it so an unchecked name is not reread needlessly.
    if not first_ok and len(second) in (36, 44) and is_known_mrz_country(second[10:13]):
        second_ok = all(verify_check_digit(second[start:stop], second[check])
                        for start, stop, check in ((0, 9, 9), (13, 19, 19), (21, 27, 27)))
    replacements = {}
    for region, good in ((header, first_ok), (body, second_ok)):
        if good:
            continue
        reads = [_read_line(image, region, recognize_line, 0, .12),
                 _read_line(image, region, recognize_line, .01, .2)]
        if (any(read is None for read in reads) or reads[0].text != reads[1].text
                or max(read.confidence for read in reads) < .90):
            return regions
        replacements[id(region)] = min(reads, key=lambda read: read.confidence)
    if not replacements:
        return regions
    new_header, new_body = replacements.get(id(header), header), replacements.get(id(body), body)
    new_first, new_second = _clean_mrz_text(new_header.text), _clean_mrz_text(new_body.text)
    checked = _checked(new_first, new_second, new_header, new_body)
    if not checked or not is_known_mrz_country(new_first[2:5]) or not is_known_mrz_country(new_second[10:13]):
        return regions
    if (existing and checked != existing) or not _preserves_checked_body(second, new_second):
        return regions
    for old, new in ((first[2:5], new_first[2:5]), (second[10:13], new_second[10:13])):
        if is_known_mrz_country(old) and old != new:
            return regions
    # A valid name has no checksum. Repairing an issuer must not rewrite it.
    if (re.fullmatch(r"[A-Z<]+", first[5:])
            and first[5:].rstrip("<") != new_first[5:].rstrip("<")):
        return regions
    return [replacements.get(id(region), region) for region in regions]
