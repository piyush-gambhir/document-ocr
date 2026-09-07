from unittest.mock import Mock

import numpy as np
import pytest

from core.ead_recovery import recover_ead_fields
from core.ocr_engine import TextRegion
from core.structured_documents import StructuredExtraction, extract_structured_document


def row(text, x=20, y=20, width=200, height=20, confidence=.99):
    return TextRegion(text, [[x, y], [x + width, y], [x + width, y + height], [x, y + height]], confidence)


def ead(*, complete=True, name='PERSON'):
    rows = [row('UNITED STATES OF AMERICA'), row('EMPLOYMENT AUTHORIZATION', y=50),
            row('Surname: EXAMPLE', y=90), row('Given Name: ' + name, y=120),
            row('Card number: SRC1234567890', y=150), row('Category: C09', y=180),
            row('Sex: M', y=210), row('Country of Birth: Canada', y=240)]
    if complete:
        rows += [row('USCIS#: 123456789', x=500, y=90),
                 row('Date of Birth: 01 JAN 1980', x=500, y=120),
                 row('Valid From: 01/01/20', x=500, y=150),
                 row('Card Expire', y=300), row('01/01/30', x=260, y=300)]
    return rows


def initial(name='PERSON'):
    return extract_structured_document(ead(complete=False, name=name))


def recognized_label(text='Card Expires', confidence=.99):
    return [row(text, x=0, y=0, width=239, height=19, confidence=confidence)]


def test_unconfirmed_missing_plane_and_complete_documents_skip_all_ocr():
    image = np.zeros((600, 1000, 3), np.uint8)
    complete_rows = ead()
    complete_rows[-2].text = 'Card Expires'
    complete = extract_structured_document(complete_rows)
    unconfirmed = StructuredExtraction('us_ead', 'US', errors=['DOCUMENT_TYPE_NOT_CONFIRMED'])
    for plane, parsed in ((None, initial()), (image, complete), (image, unconfirmed)):
        ocr, recognize = Mock(), Mock()
        assert recover_ead_fields(plane, parsed, ocr, recognize) is None
        ocr.assert_not_called()
        recognize.assert_not_called()


def test_one_unenhanced_pass_and_one_observed_label_read_recover_fields():
    image = np.zeros((600, 1000, 3), np.uint8)
    ocr = Mock(return_value=ead())
    recognize = Mock(return_value=recognized_label())
    result = recover_ead_fields(image, initial(), ocr, recognize)
    assert result.complete
    assert result.fields['uscis_number'] == '123456789'
    assert result.fields['expiry_date'] == '2030-01-01'
    assert result.checks['ocr_view_agreement']
    assert image.max() == 0
    ocr.assert_called_once_with(image)
    recognize.assert_called_once()


def test_disagreeing_names_preserve_both_evidence_values_and_require_review():
    result = recover_ead_fields(np.zeros((600, 1000, 3), np.uint8), initial('DIFFERENT'),
                                Mock(return_value=ead()), Mock(return_value=recognized_label()))
    assert result.fields['given_names'] == 'PERSON'
    assert result.errors == ['OCR_VIEW_CONFLICT_GIVEN_NAMES']
    assert not result.complete and result.confidence <= .49
    assert not result.checks['ocr_view_agreement']
    assert {item['text'] for item in result.field_evidence['given_names']} == {'PERSON', 'DIFFERENT'}


@pytest.mark.parametrize('text,confidence', [('Card Expire', .99), ('Card Expires', .89)])
def test_expiry_label_is_not_completed_by_guessing(text, confidence):
    result = recover_ead_fields(np.zeros((600, 1000, 3), np.uint8), initial(),
                                Mock(return_value=ead()), Mock(return_value=recognized_label(text, confidence)))
    assert 'expiry_date' not in result.fields
    assert 'expiry_date' in result.missing_required_fields


def test_low_confidence_new_fields_do_not_replace_original_view():
    rows = ead()
    next(row for row in rows if row.text.startswith('USCIS')).confidence = .89
    assert recover_ead_fields(np.zeros((600, 1000, 3), np.uint8), initial(),
                              Mock(return_value=rows), Mock(return_value=recognized_label())) is None


def test_unidentified_or_lower_coverage_alternative_is_ignored():
    for rows in ([row('unrelated page')], ead(complete=False)):
        recognize = Mock()
        assert recover_ead_fields(np.zeros((600, 1000, 3), np.uint8), initial(),
                                  Mock(return_value=rows), recognize) is None
        recognize.assert_not_called()


def test_already_observed_errors_are_not_cleared_by_new_pixels():
    before = initial()
    before.errors.append('DOCUMENT_COUNTRY_MISMATCH')
    result = recover_ead_fields(np.zeros((600, 1000, 3), np.uint8), before,
                                Mock(return_value=ead()), Mock(return_value=recognized_label()))
    assert 'DOCUMENT_COUNTRY_MISMATCH' in result.errors
    assert not result.complete
