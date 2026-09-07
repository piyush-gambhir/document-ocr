"""Read a boxed W-9 TIN when text detection splits or omits individual digits."""
from __future__ import annotations

import re
import cv2
import numpy as np

from .ocr_engine import TextRegion
from .structured_documents import _detect_text_type, extract_structured_document


def recover_form_fields(image, regions: list[TextRegion], recognize_line) -> list[TextRegion]:
    if _detect_text_type(regions)[0] != 'us_w9':
        return regions
    parsed = extract_structured_document(regions)
    if parsed and parsed.fields.get('taxpayer_id'):
        return regions
    output = list(regions)
    # At most two reads for each of the two labelled TIN boxes. The original
    # full image determines evidence coordinates; no expected digits are used.
    for label in ('social security number', 'employer identification number'):
        anchor = next((r for r in regions if r.text.strip().lower() == label), None)
        if not anchor or len(anchor.bbox) != 4:
            continue
        points = np.asarray(anchor.bbox)
        left, top = points.min(axis=0)
        right, bottom = points.max(axis=0)
        height = bottom - top
        if height < 8 or right - left < height * 4:
            continue
        x1, y1 = max(0, int(left - 4)), max(0, int(bottom))
        x2, y2 = min(image.shape[1], int(left + height * 18)), min(image.shape[0], int(bottom + height * 2.8))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image[y1:y2, x1:x2]
        for row in recognize_line(crop):
            # Box borders and printed hyphens can be recognized as separators.
            # Letters/guessed substitutions and non-nine-digit reads fail closed.
            if row.confidence < .8 or not re.fullmatch(r'[0-9\s|\[\]{}()_.:;\-]+', row.text):
                continue
            digits = re.sub(r'\D', '', row.text)
            if len(digits) != 9:
                continue
            if row.confidence < .9:
                # Printed box borders lower the whole-string confidence. For
                # an uncertain read, require all nine digits to agree after
                # removing long straight ruling lines and reading once more.
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
                vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((int(height * 1.6), 1), np.uint8))
                horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, int(height * 3)), np.uint8))
                cleaned = crop.copy()
                cleaned[cv2.bitwise_or(vertical, horizontal) > 0] = 255
                confirmation = recognize_line(cleaned)
                if (len(confirmation) != 1 or confirmation[0].confidence < .8
                        or not re.fullmatch(r'[0-9\s|\[\]{}()_.:;\-]+', confirmation[0].text)
                        or re.sub(r'\D', '', confirmation[0].text) != digits):
                    continue
            output.append(TextRegion(label + ': ' + digits,
                                     [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], row.confidence))
    return output
