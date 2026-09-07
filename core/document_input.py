"""Bounded PDF page loading and native text geometry in rendered-page coordinates.

PDFium is not thread-safe. Every PDF operation, including object disposal, runs
under the same process-wide lock. Native text is extraction evidence, not a
claim that a PDF is authentic or that its hidden text matches its visible ink.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import math

import cv2
import numpy as np

from .ocr_engine import TextRegion

PDF_LOCK = threading.RLock()
MAX_PAGES = 10
MAX_PAGE_PIXELS = 20_000_000
MAX_DOCUMENT_PIXELS = 40_000_000
MAX_TEXT_CHARS = 100_000
PDF_WIDTH = 1600


@dataclass
class InputPage:
    image: np.ndarray
    regions: list[TextRegion]
    number: int
    total: int


def input_bytes(source: str | bytes | Path) -> bytes:
    return Path(source).read_bytes() if isinstance(source, (str, Path)) else source


def pdf_pages(data: bytes, *, first_only: bool = False) -> list[InputPage]:
    from .preprocessor import ImageQualityError
    import pypdfium2 as pdfium

    with PDF_LOCK:
        try:
            doc = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise ImageQualityError('INVALID_PDF') from exc
        try:
            total = len(doc)
            if not total:
                raise ImageQualityError('PDF_HAS_NO_PAGES')
            if total > MAX_PAGES and not first_only:
                raise ImageQualityError('TOO_MANY_PAGES')
            output = []
            total_pixels = 0
            for index in range(1 if first_only else total):
                page = doc[index]
                textpage = bitmap = None
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ImageQualityError('INVALID_PDF_PAGE_SIZE')
                    scale = PDF_WIDTH / width
                    pixels = math.ceil(width * scale) * math.ceil(height * scale)
                    if pixels > MAX_PAGE_PIXELS:
                        raise ImageQualityError('PDF_PAGE_TOO_LARGE')
                    total_pixels += pixels
                    if total_pixels > MAX_DOCUMENT_PIXELS:
                        raise ImageQualityError('PDF_DOCUMENT_TOO_LARGE')
                    bitmap = page.render(scale=scale)
                    image = cv2.cvtColor(np.array(bitmap.to_pil().convert('RGB')), cv2.COLOR_RGB2BGR)
                    textpage = page.get_textpage()
                    regions = _native_regions(textpage, bitmap.get_posconv(page), image.shape[1], image.shape[0])
                    # Character boxes are in unrotated PDF space. On a rotated
                    # page fall back to rendered OCR until its transform is known.
                    if page.get_rotation():
                        regions = []
                    output.append(InputPage(image, regions, index + 1, total))
                finally:
                    if textpage is not None:
                        textpage.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
            return output
        except pdfium.PdfiumError as exc:
            raise ImageQualityError('INVALID_PDF') from exc
        finally:
            doc.close()


def _native_regions(textpage, converter, width: int, height: int) -> list[TextRegion]:
    from .preprocessor import ImageQualityError
    count = textpage.count_chars()
    if count > MAX_TEXT_CHARS:
        raise ImageQualityError('PDF_TEXT_TOO_LARGE')
    regions, chars, boxes = [], [], []
    line_top = line_bottom = None

    def flush():
        nonlocal line_top, line_bottom
        text = ''.join(chars).strip()
        if text and boxes:
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            regions.append(TextRegion(text, [[x0,y0],[x1,y0],[x1,y1],[x0,y1]], 1.0))
        chars.clear()
        boxes.clear()
        line_top = line_bottom = None

    for index in range(count):
        char = textpage.get_text_range(index, 1)
        if not char or char in '\r\n':
            flush()
            continue
        if char.isspace():
            chars.append(' ')
            continue
        left, bottom, right, top = textpage.get_charbox(index)
        # PDFium's own transform handles CropBox/MediaBox offsets and bitmap
        # rounding. Scaling page coordinates ourselves misaligns redaction.
        corners = [converter.to_bitmap(x, y) for x, y in
                   ((left, bottom), (right, bottom), (right, top), (left, top))]
        box = [max(0, min(p[0] for p in corners)), max(0, min(p[1] for p in corners)),
               min(width, max(p[0] for p in corners)), min(height, max(p[1] for p in corners))]
        if box[0] >= box[2] or box[1] >= box[3]:
            continue
        if boxes and (box[1] > line_bottom+3 or box[3] < line_top-3 or box[0] < boxes[-1][0]-5):
            flush()
        chars.append(char)
        boxes.append(box)
        line_top = min(line_top, box[1]) if line_top is not None else box[1]
        line_bottom = max(line_bottom, box[3]) if line_bottom is not None else box[3]
    flush()
    return regions
