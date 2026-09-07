"""Parser regressions reproduced by real JPEG/raster-PDF OCR output."""

import pytest

from core.ocr_engine import TextRegion
from core.structured_documents import extract_structured_document
from document_samples import regions


def row(text, x, y, width, height=40):
    return TextRegion(text, [[x, y], [x + width, y],
                             [x + width, y + height], [x, y + height]], .97)


@pytest.mark.parametrize("issuer", ["USASD", "USA SD", "USA\nSD"])
def test_joined_us_issuer_still_requires_registered_state_and_title(issuer):
    result = extract_structured_document(regions(
        "DRIVER LICENSE", issuer, "LN: SAMPLE", "DL: A1234567",
        "DOB: 03/15/1990", "EXP: 06/01/2030",
    ))
    assert result.issuing_region == "SD"
    assert result.complete
    assert extract_structured_document(regions(issuer, "DL: A1234567")) is None


@pytest.mark.parametrize("issuer", ["USAZZ", "USASDA", "AUSASD"])
def test_joined_issuer_does_not_accept_unknown_state_or_partial_token(issuer):
    assert extract_structured_document(regions("DRIVER LICENSE", issuer)) is None


@pytest.mark.parametrize("scale", [.5, 1, 2])
def test_issue_date_survives_small_overlapping_ocr_boxes(scale):
    # Observed after raster-PDF contrast normalization: the correct date's
    # box overlaps the ISS label by 34.5px in the tilted label's own axes.
    observed = [
        TextRegion("4a ISS", [[1092, 256], [1250, 246], [1253, 298], [1095, 308]], .93),
        TextRegion("07/06/2024", [[1219, 240], [1567, 240], [1567, 303], [1219, 303]], .96),
        TextRegion("4b EXP 07/06/2029", [[1087, 308], [1542, 300], [1543, 364], [1088, 371]], .95),
    ]
    for region in observed:
        region.bbox = [[x * scale, y * scale] for x, y in region.bbox]
    result = extract_structured_document(regions("USA SD DRIVER LICENSE") + observed)
    assert result.fields["issue_date"] == "2024-07-06"
    assert result.fields["expiry_date"] == "2029-07-06"
    assert result.field_evidence["issue_date"][0]["text"] == "07/06/2024"


def test_blank_issue_date_does_not_borrow_expiry_from_next_horizontal_field():
    result = extract_structured_document(regions("USA SD DRIVER LICENSE") + [
        row("4a ISS", 100, 100, 100),
        row("4b EXP", 230, 100, 100),
        row("07/06/2029", 320, 100, 200),
    ])
    assert "issue_date" not in result.fields
    assert result.fields["expiry_date"] == "2029-07-06"


@pytest.mark.parametrize("x,width", [(110, 60), (150, 250)])
def test_overlapping_value_must_extend_right_and_only_overlap_a_small_amount(x, width):
    result = extract_structured_document(regions("USA SD DRIVER LICENSE") + [
        row("4a ISS", 100, 100, 100), row("07/06/2024", x, 100, width),
    ])
    assert "issue_date" not in result.fields


@pytest.mark.parametrize("inline", [False, True])
def test_joined_expiry_label_is_recognized_without_borrowing_it_for_issue_date(inline):
    expiry = [row("ExpiresOn 06/01/2030", 100, 200, 500)] if inline else [
        row("ExpiresOn", 100, 200, 150), row("06/01/2030", 100, 250, 200),
    ]
    result = extract_structured_document(regions("UNITED STATES PASSPORT CARD") + [
        row("Date of Issue", 100, 150, 180), *expiry,
    ])
    assert result.fields["expiry_date"] == "2030-06-01"
    assert "issue_date" not in result.fields


def test_long_date_below_short_tilted_label_uses_top_edge_centre():
    # Saved PDF label and a fresh pixel reread have slightly different angles.
    # The far-right corner crosses the old overlap limit although the date's
    # top-edge centre is correctly below the label.
    result = extract_structured_document(regions("UNITED STATES PASSPORT CARD") + [
        TextRegion("Expires", [[1105, 784], [1250, 790], [1248, 831], [1103, 825]], .99),
        TextRegion("29 NOV 2019", [[1104, 824], [1448, 824], [1448, 884], [1104, 884]], .95),
    ])
    assert result.fields["expiry_date"] == "2019-11-29"


@pytest.mark.parametrize("mutation", ["wrong_column", "too_high", "intervening_label"])
def test_top_edge_centre_does_not_borrow_an_unrelated_date(mutation):
    label = TextRegion("Expires", [[1105, 784], [1250, 790], [1248, 831], [1103, 825]], .99)
    date = row("29 NOV 2019", 1104, 824, 344, 60)
    rows = [label, date]
    if mutation == "wrong_column":
        date.bbox = [[x - 400, y] for x, y in date.bbox]
    elif mutation == "too_high":
        date.bbox = [[x, y - 100] for x, y in date.bbox]
    else:
        date.bbox = [[x, y + 80] for x, y in date.bbox]
        rows.append(row("Date of Issue", 1105, 840, 180, 40))
    result = extract_structured_document(regions("UNITED STATES PASSPORT CARD") + rows)
    assert "expiry_date" not in result.fields
