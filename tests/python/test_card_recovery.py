from unittest.mock import Mock, patch

import numpy as np
import pytest

from core.card_recovery import _card_text_box, _read_box, _read_expiry_date, recover_card_fields
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


def truncated_expiry():
    rows = card()
    rows[-1].text = '01 JAN 203'
    return rows


def test_truncated_expiry_uses_one_observed_box_and_preserves_existing_evidence():
    rows = truncated_expiry()
    before = extract_structured_document(rows)
    reader = Mock(return_value=[row('01 JAN 2030', x=0, y=0, width=197, height=19)])
    detector = Mock()
    image = np.zeros((1000, 1200, 3), np.uint8)
    output = recover_card_fields(image, rows, detector, reader)
    after = extract_structured_document(output)
    assert after.complete and after.fields['expiry_date'] == '2030-01-01'
    assert output[:len(rows)] == rows
    assert all(after.fields[key] == value for key, value in before.fields.items())
    assert all(after.field_evidence[key] == value for key, value in before.field_evidence.items())
    assert after.field_evidence['expiry_date'][0]['bbox'] == [[421, 435], [619, 435], [619, 455], [421, 455]]
    assert reader.call_args.args[0].shape[:2] == (20, 198)
    reader.assert_called_once()
    detector.assert_not_called()


@pytest.mark.parametrize('second,confidence,accepted', [
    ('01 JAN 2030', .94, True), ('01 JAN 2031', .99, False),
    ('01 JAN 2030', .89, False), ('01 JAN 203', .99, False),
])
def test_denoised_date_requires_agreement_and_high_confidence(second, confidence, accepted):
    rows = truncated_expiry()
    reader = Mock(side_effect=[
        [row('01 JAN 2030', x=0, y=0, width=197, height=19, confidence=.86)],
        [row(second, x=0, y=0, width=197, height=19, confidence=confidence)],
    ])
    detector = Mock(return_value=[])
    output = recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, detector, reader)
    assert (output is not rows) is accepted
    assert reader.call_count == 2
    assert detector.call_count == (0 if accepted else 1)
    if accepted:
        assert extract_structured_document(output).field_evidence['expiry_date'][0]['confidence'] == .94


@pytest.mark.parametrize('text,confidence', [('02 JAN 2030', .99), ('01 JAN 203', .99), ('01 JAN 2030', .79)])
def test_unresolved_or_changed_date_prefix_skips_second_read(text, confidence):
    rows = truncated_expiry()
    reader = Mock(return_value=[row(text, confidence=confidence)])
    output = recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, Mock(return_value=[]), reader)
    assert output is rows
    reader.assert_called_once()


@pytest.mark.parametrize('mutation', ['ambiguous_date', 'ambiguous_label', 'wrong_column', 'outside_image', 'low_label_confidence'])
def test_expiry_reread_rejects_ambiguous_or_unsafe_geometry(mutation):
    rows = truncated_expiry()
    if mutation == 'ambiguous_date':
        rows.append(row('01 JAN 202', x=430, y=455))
    elif mutation == 'ambiguous_label':
        rows.append(row('Expires', x=430, y=460))
    elif mutation == 'wrong_column':
        rows[-1] = row('01 JAN 203', x=100, y=435)
    elif mutation == 'outside_image':
        rows[-2] = row('Expires', x=1090, y=410)
        rows[-1] = row('01 JAN 203', x=1090, y=435)
    else:
        rows[-2].confidence = .89
    reader = Mock()
    output = recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, Mock(return_value=[]), reader)
    assert output is rows
    reader.assert_not_called()


@pytest.mark.parametrize('raw_text,raw_confidence,accepted', [
    ('01 JAN 2030', .97, True), ('02 JAN 2030', .99, False), ('01 JAN 2030', .89, False),
])
def test_raw_plane_reread_requires_same_prefix_and_high_confidence(raw_text, raw_confidence, accepted):
    rows = truncated_expiry()
    image = np.zeros((1000, 1200, 3), np.uint8)
    original = np.full_like(image, 255)
    reader = Mock(side_effect=[
        [row('01 JAN 203', x=0, y=0, width=197, height=19, confidence=.95)],
        [row(raw_text, x=0, y=0, width=197, height=19, confidence=raw_confidence)],
    ])
    detector = Mock(return_value=[])
    output = recover_card_fields(image, rows, detector, reader, unenhanced_image=original)
    assert (output is not rows) is accepted
    assert reader.call_count == 2
    assert reader.call_args_list[0].args[0].max() == 0
    assert reader.call_args_list[1].args[0].min() == 255
    if accepted:
        assert extract_structured_document(output).fields['expiry_date'] == '2030-01-01'
        detector.assert_not_called()


def test_raw_plane_with_different_geometry_cannot_supply_evidence():
    rows = truncated_expiry()
    reader = Mock(return_value=[row('01 JAN 203', confidence=.95)])
    image = np.zeros((1000, 1200, 3), np.uint8)
    output = recover_card_fields(image, rows, Mock(return_value=[]), reader,
                                 unenhanced_image=np.zeros((800, 1200, 3), np.uint8))
    assert output is rows
    reader.assert_called_once()


def test_conflicting_complete_reads_cannot_fall_through_to_a_third_raw_read():
    rows = truncated_expiry()
    reader = Mock(side_effect=[
        [row('01 JAN 2030', confidence=.86)], [row('01 JAN 2031', confidence=.99)],
    ])
    image = np.zeros((1000, 1200, 3), np.uint8)
    output = recover_card_fields(image, rows, Mock(return_value=[]), reader,
                                 unenhanced_image=np.ones_like(image))
    assert output is rows
    assert reader.call_count == 2


def test_long_expiry_box_can_overlap_a_slightly_tilted_label():
    rows = truncated_expiry()
    rows[-2].bbox = [[430, 410], [610, 418], [610, 448], [430, 440]]
    rows[-1].bbox = [[440, 442], [710, 442], [710, 483], [440, 483]]
    reader = Mock(return_value=[row('01 JAN 2030', x=0, y=0, width=296, height=40)])
    output = _read_expiry_date(np.zeros((1000, 1200, 3), np.uint8), rows, reader)
    assert len(output) == 1 and output[0].text == '01 JAN 2030'
    reader.assert_called_once()


def test_tilted_label_recovery_reaches_the_structured_expiry_field():
    rows = truncated_expiry()
    rows[-2].bbox = [[430, 410], [610, 418], [610, 448], [430, 440]]
    rows[-1].bbox = [[440, 442], [710, 442], [710, 483], [440, 483]]
    before = extract_structured_document(rows)
    reader = Mock(return_value=[row('01 JAN 2030', x=0, y=0, width=296, height=40)])
    detector = Mock()
    output = recover_card_fields(np.zeros((1000, 1200, 3), np.uint8), rows, detector, reader)
    after = extract_structured_document(output)
    assert after.complete and after.fields['expiry_date'] == '2030-01-01'
    assert all(after.fields[key] == value for key, value in before.fields.items())
    assert all(after.field_evidence[key] == value for key, value in before.field_evidence.items())
    reader.assert_called_once()
    detector.assert_not_called()
