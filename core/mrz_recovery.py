"""Bounded, geometry-based re-reading of a damaged passport MRZ.

Only a checksum-valid TD3 pair is admitted; identifiers are never invented.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .mrz_parser import _clean_mrz_text, parse_mrz, verify_check_digit
from .ocr_engine import TextRegion

# A complete surname/given-name header with an observed padding terminator.
_PADDED_HEADER = re.compile(r'P[A-Z<][A-Z<]{3}[A-Z]+(?:<[A-Z]+)*<<[A-Z]+(?:<[A-Z]+)*<{2,}')
_ANCHOR = re.compile(r'[A-Z0-9<]{28,44}')
_LINE_TWO = re.compile(r'[A-Z0-9<]{9}[0-9][A-Z<]{3}[0-9]{7}[MF<][0-9]{7}[A-Z0-9<]{16}')
_LINE_TWO_PREFIX = re.compile(r'[A-Z0-9<]{9}[0-9][A-Z]{3}[0-9]{7}[MF<][0-9]{7}[A-Z0-9<]{0,15}')


def _checked_line_two_prefix(text: str) -> bool:
    """Locate a truncated row from observed fields, without filling its suffix."""
    return bool(_LINE_TWO_PREFIX.fullmatch(text)
                and verify_check_digit(text[:9], text[9])
                and verify_check_digit(text[13:19], text[19])
                and verify_check_digit(text[21:27], text[27]))


def _anchors(regions: list[TextRegion]) -> list[TextRegion]:
    result = []
    for row in regions:
        text = _clean_mrz_text(row.text)
        if (len(row.bbox) == 4 and _ANCHOR.fullmatch(text)
                and (text.count('<') >= 2 or _LINE_TWO.fullmatch(text) or _checked_line_two_prefix(text))
                and (not text.startswith('P') or _LINE_TWO.fullmatch(text) or _checked_line_two_prefix(text))):
            result.append(row)
    return result


def _read_crop(image, src, width, height, reader) -> list[TextRegion]:
    """Read a deskewed crop and map evidence back to page coordinates."""
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    transform = cv2.getPerspectiveTransform(np.asarray(src, np.float32), dst)
    if abs(np.linalg.det(transform)) < 1e-12:
        return []
    crop = cv2.warpPerspective(image, transform, (width, height), borderValue=(255, 255, 255))
    inverse = np.linalg.inv(transform)
    recovered = []
    for region in reader(crop):
        text = _clean_mrz_text(region.text)
        if 20 <= len(text) < 44 and _PADDED_HEADER.fullmatch(text):
            # Only omitted trailing fillers can be recovered from this rule.
            text = text.ljust(44, '<')
        points = np.asarray(region.bbox, np.float32)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        points = cv2.perspectiveTransform(points[None], inverse)[0]
        recovered.append(TextRegion(text, points.round().astype(int).tolist(), region.confidence))
    return recovered


def recover_passport_mrz(image, regions: list[TextRegion], ocr, recognize_line=None) -> list[TextRegion]:
    existing = parse_mrz(regions)
    if existing and existing.overall_checksum_valid and 'MRZ_NAME_PADDING_NOISE' not in existing.errors:
        return regions
    long_rows = [r for r in regions if len(r.text) >= 8 and len(r.bbox) == 4]
    vertical_rows = [r for r in long_rows if
                     abs(r.bbox[1][1] - r.bbox[0][1]) > 2 * abs(r.bbox[1][0] - r.bbox[0][0])
                     or (max(p[1] for p in r.bbox) - min(p[1] for p in r.bbox)) >
                     2 * (max(p[0] for p in r.bbox) - min(p[0] for p in r.bbox))]
    if len(vertical_rows) >= 4 and len(vertical_rows) / len(long_rows) >= .6:
        # Sideways lines cannot reliably be recognized or paired in page-Y
        # order. Try each quarter-turn, keeping original-page evidence boxes.
        h, w = image.shape[:2]
        corners = [(0, 0), (w - 1, 0), (w - 1, h - 1), (0, h - 1)]
        for order in ((3, 0, 1, 2), (1, 2, 3, 0)):
            recovered = _read_crop(image, [corners[i] for i in order], h, w, ocr)
            parsed = parse_mrz(recovered)
            if parsed and parsed.overall_checksum_valid:
                return recovered
        return regions  # The two-read budget is exhausted.
    anchors = _anchors(regions)
    band_budget = 2
    if not anchors and any(re.search(r'\bPASSPORT\b', r.text, re.I) for r in regions):
        # A small passport in a large photo can lose its entire MRZ during
        # detection downscaling. Focus on confident visible document text once.
        body = [r for r in regions if len(r.text) >= 4 and r.confidence >= .85 and len(r.bbox) == 4]
        if len(body) >= 5:
            points = np.asarray([p for r in body for p in r.bbox], np.float32)
            left, top = points.min(axis=0)
            right, bottom = points.max(axis=0)
            bw, bh = right - left, bottom - top
            h, w = image.shape[:2]
            x1, y1 = max(0, int(left - bw * .2)), max(0, int(top - bh * .15))
            x2, y2 = min(w, int(right + bw * .2)), min(h, int(bottom + bh * .4))
            if bw >= 200 and bh >= 100 and 0 < (x2 - x1) * (y2 - y1) < w * h * .75:
                recovered = _read_crop(image, [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                                       x2 - x1, y2 - y1, ocr)
                parsed = parse_mrz(recovered)
                if parsed and parsed.overall_checksum_valid:
                    return recovered
                # Detection may reveal only the beginning of the bottom row.
                # Reuse its original-page geometry for one final band read;
                # never insert unobserved suffix characters or check digits.
                anchors = _anchors(recovered)
                band_budget -= 1
    # At most two band reads, plus one recognition-only fallback per full anchor.
    for anchor in sorted(anchors, key=lambda r: len(_clean_mrz_text(r.text)), reverse=True)[:band_budget]:
        box = np.asarray(anchor.bbox, dtype=np.float32)
        if box.shape != (4, 2) or not np.isfinite(box).all():
            continue
        tl, tr, br, bl = box
        vertical = ((bl - tl) + (br - tr)) / 2
        width, line_height = float(np.linalg.norm(tr - tl)), float(np.linalg.norm(vertical))
        if width < 100 or line_height < 5 or width / line_height < 8:
            continue
        # Include the line above and a little border. Deskew using detected text,
        # which still works when a document occupies a small part of a photograph.
        # A TD3 line has 44 fixed-width characters. A partial detection must not
        # clip the unseen right-hand characters from the recovery crop.
        anchor_text = _clean_mrz_text(anchor.text)
        extension = (44 / len(anchor_text) - 1) * (tr - tl)
        tr, br = tr + extension, br + extension
        if _checked_line_two_prefix(anchor_text):
            # A truncated detector box can end inside a character. Leave one
            # character of pixels at either edge of the predicted full row.
            margin = (tr - tl) / 44
            tl, bl, tr, br = tl - margin, bl - margin, tr + margin, br + margin
        full_width = float(np.linalg.norm(tr - tl))
        w = min(1600, int(full_width))
        h = max(20, int(line_height * 4 * w / full_width))
        src = [tl - 2.5 * vertical, tr - 2.5 * vertical,
               br + .5 * vertical, bl + .5 * vertical]
        recovered = _read_crop(image, src, w, h, ocr)
        # The original full-width line two can be better than the cropped reading.
        # Evaluate complete re-read first, then each recovered header with its anchor.
        candidates = [recovered] + [[r, anchor] for r in recovered
                                    if _PADDED_HEADER.fullmatch(_clean_mrz_text(r.text))]
        def candidate_reads():
            yield from candidates
            if recognize_line is None or not _LINE_TWO.fullmatch(_clean_mrz_text(anchor.text)):
                return
            # A complete bottom line also localizes the name line immediately
            # above it. Bypass detection when that line was missed in the band.
            line_src = [tl - 1.1 * vertical, tr - 1.1 * vertical,
                        tr + .1 * vertical, tl + .1 * vertical]
            line_height_px = max(10, int(line_height * 1.2 * w / full_width))
            header = _read_crop(image, line_src, w, line_height_px, recognize_line)
            for row in header:
                # Names have no check digit: require clean syntax, observed name
                # termination, and high recognition confidence before admission.
                if row.confidence >= .9 and _PADDED_HEADER.fullmatch(row.text):
                    yield [row, anchor]

        for candidate in candidate_reads():
            parsed = parse_mrz(candidate)
            if not parsed or not parsed.overall_checksum_valid:
                continue
            if existing and existing.overall_checksum_valid and 'MRZ_NAME_PADDING_NOISE' in parsed.errors:
                continue
            if existing and existing.passport_number.value != parsed.passport_number.value:
                continue
            # Preserve visual text and its coordinates; replace only MRZ-like rows.
            visual = [r for r in regions if not (
                _ANCHOR.fullmatch(_clean_mrz_text(r.text))
                and ('<' in _clean_mrz_text(r.text) or _LINE_TWO.fullmatch(_clean_mrz_text(r.text))))]
            mrz_rows = [r for r in candidate if _ANCHOR.fullmatch(_clean_mrz_text(r.text))]
            return visual + mrz_rows
    return regions
