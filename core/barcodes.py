"""Local barcode decoding and bounded AAMVA PDF417 payload parsing.

Annex D of the AAMVA 2025 DL/ID standard defines the header/subfile directory.
Decoding a barcode establishes neither issuer authenticity nor a signature.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field

import numpy as np


@dataclass
class BarcodeResult:
    format: str
    text: str
    bbox: list[list[int]]
    raw_bytes: bytes = b""


def barcode_decoder_available() -> bool:
    return importlib.util.find_spec("zxingcpp") is not None


def decode_barcodes(image: np.ndarray) -> list[BarcodeResult]:
    """Decode PDF417/other barcodes locally; an optional missing backend yields []."""
    if not barcode_decoder_available():
        return []
    import zxingcpp

    # OCR images are BGR. Grayscale conversion also makes channel ordering
    # irrelevant to the native decoder and avoids an additional cv2 dependency.
    if image.ndim == 3:
        image = np.mean(image[:, :, :3], axis=2).astype(np.uint8)
    results = []
    for barcode in zxingcpp.read_barcodes(np.ascontiguousarray(image)):
        if not barcode.valid:
            continue
        position = barcode.position
        bbox = [[int(point.x), int(point.y)] for point in (position.top_left, position.top_right, position.bottom_right, position.bottom_left)]
        results.append(BarcodeResult(str(barcode.format), barcode.text, bbox, bytes(barcode.bytes)))
    return results


decode = decode_barcodes


@dataclass
class AAMVAResult:
    document_type: str
    issuer_id: str
    version: int
    jurisdiction_version: int
    elements: dict[str, str]
    errors: list[str] = field(default_factory=list)


_HEADER = re.compile(rb"@\n\x1e\rANSI ([0-9]{6})([0-9]{2})([0-9]{2})([0-9]{2})")


def parse_aamva(barcode: BarcodeResult | str) -> AAMVAResult | None:
    """Parse directory offsets against original bytes, not stripped OCR text.

    None means this is not an AAMVA payload. Recognizable malformed payloads
    raise ValueError so callers can surface corrupt barcode evidence.
    """
    try:
        if isinstance(barcode, str):
            if not barcode.startswith("@") or "ANSI " not in barcode[:16]:
                return None
            data = barcode.encode("latin-1")
        else:
            if not barcode.raw_bytes and (not barcode.text.startswith("@") or "ANSI " not in barcode.text[:16]):
                return None
            data = barcode.raw_bytes or barcode.text.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError("INVALID_AAMVA_ENCODING") from None
    if not data.startswith(b"@") or b"ANSI " not in data[:16]:
        return None
    header = _HEADER.match(data)
    if header is None:
        raise ValueError("INVALID_AAMVA_HEADER")
    issuer, version, jurisdiction, count = header.groups()
    version_number = int(version)
    if not 1 <= version_number <= 11:
        raise ValueError("UNSUPPORTED_AAMVA_VERSION")
    count_number = int(count)
    directory_end = header.end() + 10 * count_number
    if not count_number or directory_end > len(data):
        raise ValueError("INVALID_AAMVA_DIRECTORY")
    subfiles: list[tuple[str, int, int]] = []
    for index in range(count_number):
        entry = data[header.end() + 10 * index:header.end() + 10 * (index + 1)]
        if not re.fullmatch(rb"[A-Z]{2}[0-9]{8}", entry):
            raise ValueError("INVALID_AAMVA_DIRECTORY")
        kind, offset, length = entry[:2].decode("ascii"), int(entry[2:6]), int(entry[6:10])
        end = offset + length
        if offset < directory_end or length < 2 or end > len(data) or data[offset:offset + 2] != entry[:2]:
            raise ValueError("INVALID_AAMVA_SUBFILE_BOUNDS")
        if any(offset < old_end and start < end for _, start, old_end in subfiles):
            raise ValueError("OVERLAPPING_AAMVA_SUBFILES")
        subfiles.append((kind, offset, end))
    identities = [(kind, start, end) for kind, start, end in subfiles if kind in ("DL", "ID")]
    if len(identities) != 1:
        raise ValueError("AMBIGUOUS_AAMVA_DOCUMENT_TYPE")
    kind, start, end = identities[0]
    # Annex D.6 specifies ISO 8859-1. Offsets count bytes, including accented
    # Latin characters; UTF-8 encoding would shift the subfile boundaries.
    content = data[start + 2:end].decode("latin-1")
    elements: dict[str, str] = {}
    errors: list[str] = []
    for record in re.split(r"[\r\n]", content):
        if not record:
            continue
        if not re.fullmatch(r"[A-Z]{3}[ -~\xa0-\xff]*", record):
            raise ValueError("INVALID_AAMVA_ELEMENT")
        key, value = record[:3], record[3:].strip()
        if key in elements and elements[key] != value:
            errors.append(f"CONFLICTING_AAMVA_ELEMENT_{key}")
        else:
            elements[key] = value
    return AAMVAResult("us_driver_license" if kind == "DL" else "us_state_id", issuer.decode("ascii"), version_number, int(jurisdiction), elements, errors)
