import numpy as np
import pytest

from core.barcodes import BarcodeResult, decode_barcodes, parse_aamva
from document_samples import aamva_payload


@pytest.mark.parametrize("kind, expected", [("DL", "us_driver_license"), ("ID", "us_state_id")])
@pytest.mark.parametrize("version", [8, 9, 10, 11])
def test_versioned_aamva_directory_parsing(kind, expected, version):
    result = parse_aamva(aamva_payload(kind=kind, version=version))
    assert result.document_type == expected
    assert result.version == version
    assert result.issuer_id == "636000"
    assert result.elements["DAQ"] == "T64235789"
    assert result.elements["DAK"] == "023269000"
    assert "ZVA" not in result.elements


@pytest.mark.parametrize("payload, error", [
    (aamva_payload()[:21], "INVALID_AAMVA_DIRECTORY"),
    (aamva_payload().replace("DL0041", "DL9999", 1), "INVALID_AAMVA_SUBFILE_BOUNDS"),
    (aamva_payload().replace("DL0041", "DL0000", 1), "INVALID_AAMVA_SUBFILE_BOUNDS"),
    (aamva_payload()[:-1], "INVALID_AAMVA_SUBFILE_BOUNDS"),
    (aamva_payload(version=12), "UNSUPPORTED_AAMVA_VERSION"),
    (aamva_payload().replace("@\n\x1e\r", "@\n\n\r", 1), "INVALID_AAMVA_HEADER"),
])
def test_malformed_payloads_fail_without_partial_field_extraction(payload, error):
    with pytest.raises(ValueError, match=error):
        parse_aamva(payload)


def test_raw_bytes_preserve_directory_offsets_when_display_text_is_escaped():
    payload = aamva_payload()
    barcode = BarcodeResult("PDF417", payload.replace("\n", "<LF>"), [], payload.encode("ascii"))
    assert parse_aamva(barcode).elements["DCS"] == "SAMPLE"


def test_latin1_names_follow_the_standard_without_shifting_subfile_offsets():
    payload = aamva_payload(overrides={"DCS": "GARCÍA"})
    assert parse_aamva(payload).elements["DCS"] == "GARCÍA"
    assert parse_aamva(BarcodeResult("PDF417", "", [], payload.encode("latin-1"))).elements["DCS"] == "GARCÍA"


def test_conflicting_duplicate_fields_are_reported():
    payload = aamva_payload(extra_subfile=False)
    payload = payload[:-1] + "\nDCSOTHER\r"
    payload = payload[:27] + f"{len(payload) - 31:04d}" + payload[31:]
    result = parse_aamva(payload)
    assert result.elements["DCS"] == "SAMPLE"
    assert "CONFLICTING_AAMVA_ELEMENT_DCS" in result.errors


@pytest.mark.parametrize("payload", ["https://example.test", "其他条码数据", BarcodeResult("PDF417", "其他条码数据", [])])
def test_non_aamva_barcode_is_ignored(payload):
    assert parse_aamva(payload) is None


def test_real_pdf417_image_round_trip():
    zxingcpp = pytest.importorskip("zxingcpp")
    payload = aamva_payload()
    barcode = zxingcpp.create_barcode(payload.encode("ascii"), zxingcpp.BarcodeFormat.PDF417)
    bitmap = zxingcpp.write_barcode_to_image(barcode, scale=3)
    image = np.asarray(bitmap)
    decoded = decode_barcodes(image)
    assert len(decoded) == 1
    assert decoded[0].raw_bytes == payload.encode("ascii")
    assert len(decoded[0].bbox) == 4
    assert parse_aamva(decoded[0]).elements["DAQ"] == "T64235789"
    from core.structured_documents import extract_structured_document
    assert extract_structured_document([], barcodes=decoded).complete
    assert decode_barcodes(np.full((100, 200), 255, dtype=np.uint8)) == []
