from unittest.mock import Mock, patch

import numpy as np
import pytest

from core.card_recovery import _card_text_box, _read_box, recover_card_fields
from core.ocr_engine import TextRegion
from core.structured_documents import extract_structured_document


def row(text, x=150, y=100, width=180, height=20, confidence=.99):
    return TextRegion(text, [[x, y], [x + width, y], [x + width, y + height], [x, y + height]], confidence)


def card(*, label='Passport Card no.', number='C12345678', expiry=True):
    rows = [row('UNITED STATES OF AMERICA', x=100, width=600),
            row('PASSPORT CARD', y=140), row(label, x=450, y=180),
            row(number, x=450, y=205),
            row('Surname', y=250), row('EXAMPLE', y=275),
            row('Given Names', y=310), row('PERSON', y=335),
            row('Date of Birth', x=430, y=300), row('01 JAN 1980', x=430, y=325),
            row('Sex', x=430, y=350), row('M', x=430, y=375)]
    if expiry:
        rows += [row('Expires', x=430, y=410), row('01 JAN 2030', x=430, y=435)]
    return rows


def test_complete_or_unidentified_cards_do_not_trigger_rereads():
    image = np.zeros((1000, 1200, 3), np.uint8)
    for rows in (card(), [row('Passport Card no.'), row('C12345678')]):
        ocr, recognize = Mock(), Mock()
        assert recover_card_fields(image, rows, ocr, recognize) is rows
        ocr.assert_not_called()
        recognize.assert_not_called()


def test_number_label_is_reread_from_pixels_without_spelling_repair():
    image = np.zeros((1000, 1200, 3), np.uint8)
    rows = card(label='Passpont Card no.')
    recognize = Mock(return_value=[row('Passport Card no.', x=0, y=0, width=179, height=19, confidence=.94)])
    ocr = Mock()
    result = recover_card_fields(image, rows, ocr, recognize)
    assert extract_structured_document(result).fields['document_number'] == 'C12345678'
    assert result[:len(rows)] == rows
    assert result[-1].bbox == [[446, 180], [634, 180], [634, 200], [446, 200]]
    assert image.max() == 0
    recognize.assert_called_once()
    ocr.assert_not_called()


@pytest.mark.parametrize('label,confidence', [('Passpont Card no.', .99), ('Passport Card no.', .89)])
def test_uncertain_or_still_misspelled_label_cannot_admit_a_number(label, confidence):
    rows = card(label='Passpont Card no.')
    reader = Mock(return_value=[row(label, confidence=confidence)])
    ocr = Mock(return_value=[])
    assert recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, ocr, reader) is rows
    reader.assert_called_once()
    ocr.assert_called_once()


def test_label_recovery_cannot_promote_a_low_confidence_number():
    rows = card(label='Passpont Card no.')
    rows[3].confidence = .6
    reader = Mock(return_value=[row('Passport Card no.', x=0, y=0, width=179, height=19)])
    assert recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, Mock(), reader) is rows


def test_cluster_read_maps_back_to_original_coordinates_and_rejects_bad_geometry():
    image = np.zeros((1000, 1200, 3), np.uint8)
    rows = card(expiry=False)
    corners, width, height = _card_text_box(image, rows)
    reader = Mock(return_value=[row('OBSERVED', x=0, y=0, width=width - 1, height=height - 1)])
    recovered = _read_box(image, corners, width, height, reader)
    np.testing.assert_allclose(recovered[0].bbox, corners, atol=.51)
    assert reader.call_args.args[0].shape[:2] == (height, width)
    reader.reset_mock()
    assert _read_box(image, [[0, 0]] * 4, 200, 40, reader) == []
    assert _read_box(image, corners, 100_000, 40, reader) == []
    reader.assert_not_called()


def test_conflicting_cluster_reread_keeps_original_fields():
    image = np.zeros((1000, 1200, 3), np.uint8)
    rows = card(expiry=False)
    conflicting = card()
    conflicting[5].text = 'DIFFERENT'
    reader = Mock(return_value=conflicting)
    output = recover_card_fields(image, rows, reader, Mock())
    assert output is rows
    reader.assert_called_once()


@pytest.mark.parametrize('confidence,accepted', [(.99, True), (.89, False)])
def test_cluster_adds_only_complete_high_confidence_fields(confidence, accepted):
    image = np.zeros((1000, 1200, 3), np.uint8)
    rows = card(expiry=False)
    reread = card()
    reread[-1].confidence = confidence
    reader, recognize = Mock(return_value=reread), Mock()
    output = recover_card_fields(image, rows, reader, recognize)
    assert (output is not rows) is accepted
    if accepted:
        before, after = extract_structured_document(rows), extract_structured_document(output)
        assert after.complete and after.fields['expiry_date'] == '2030-01-01'
        assert all(after.fields[key] == value for key, value in before.fields.items())
    reader.assert_called_once()
    recognize.assert_not_called()


def test_small_or_unbounded_clusters_skip_full_ocr():
    image = np.zeros((1000, 1200, 3), np.uint8)
    rows = card(expiry=False)
    rows[0].confidence = .7
    reader = Mock()
    assert recover_card_fields(image, rows, reader, Mock()) is rows
    reader.assert_not_called()


def test_unrelated_reread_watermarks_cannot_replace_previously_correct_names():
    rows = card(expiry=False)
    reread = card()
    reread[4] = row('Surname', y=250, height=10)
    reread.append(row('EXEMPLAR', x=335, y=246, width=200, height=35))
    # The reread alone correctly rejects the large watermark next to its small
    # surname label. Merging every row would make the original larger label
    # borrow that watermark as an inline surname.
    assert extract_structured_document(reread).fields['surname'] == 'EXAMPLE'
    assert extract_structured_document(rows + reread).fields['surname'] == 'EXEMPLAR'
    with patch('core.card_recovery._read_box', return_value=reread):
        output = recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, Mock(), Mock())
    result = extract_structured_document(output)
    assert result.complete and result.fields['surname'] == 'EXAMPLE'
    assert all(row.text != 'EXEMPLAR' for row in output)
