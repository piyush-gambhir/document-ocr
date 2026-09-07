from unittest.mock import Mock

import numpy as np
import pytest

from core.form_recovery import recover_form_fields
from core.mrz_parser import parse_mrz
from core.mrz_recovery import recover_passport_mrz
from core.ocr_engine import TextRegion
from core.preprocessor import ImageQualityError, _check_blur, _check_resolution
from core.structured_documents import extract_structured_document

FIRST = 'P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<'
SECOND = 'L898902C36UTO7408122F1204159ZE184226B<<<<<10'


def row(text, x=10, y=10, width=500, height=25, confidence=.99):
    return TextRegion(text, [[x, y], [x+width, y], [x+width, y+height], [x, y+height]], confidence)


def test_sideways_mrz_pairs_follow_local_line_axes():
    # Map upright text back through a quarter-turn: page-Y order is reversed.
    def rotate(r):
        return TextRegion(r.text, [[y, 1000-x] for x, y in r.bbox], r.confidence)
    first, second = rotate(row(FIRST, y=10)), rotate(row(SECOND, y=50))
    parsed = parse_mrz([second, first])
    assert parsed and parsed.overall_checksum_valid
    assert parsed.raw_lines == (FIRST, SECOND)
    # An unrelated distant bottom line must not pair with the header.
    second.bbox = [[x+400, y] for x, y in second.bbox]
    assert parse_mrz([second, first]) is None


def test_orientation_recovery_keeps_coordinates_and_limits_inference():
    rs = [TextRegion('SIDEWAYS TEXT', [[x, 30], [x, 450], [x-25, 450], [x-25, 30]], .8)
          for x in (200, 240, 280, 320)]
    reader = Mock(return_value=[row(FIRST, y=30), row(SECOND, y=70)])
    output = recover_passport_mrz(np.zeros((600, 500, 3), np.uint8), rs, reader)
    assert parse_mrz(output).overall_checksum_valid
    assert output[0].bbox != reader.return_value[0].bbox
    reader.assert_called_once()
    reader = Mock(return_value=[])
    assert recover_passport_mrz(np.zeros((600, 500, 3), np.uint8), rs, reader) is rs
    assert reader.call_count == 2


def w9_rows():
    return [row('W-9'), row('Request for Taxpayer', y=40), row('Form', x=700, y=40),
            row('Identification Number and Certification', y=70),
            row('Social security number', x=600, y=150, width=200),
            row('Employer identification number', x=600, y=240, width=250)]


def test_boxed_tin_recovery_requires_all_digits_and_never_edits_input_pixels():
    image = np.zeros((500, 1100, 3), np.uint8)
    reader = Mock(side_effect=[[row('123 | 45 - 6789')], []])
    output = recover_form_fields(image, w9_rows(), reader)
    assert extract_structured_document(output).fields['taxpayer_id'] == '123456789'
    assert image.max() == 0
    assert reader.call_count == 2


@pytest.mark.parametrize('text,confidence', [('12345678', .99), ('1234567890', .99),
                                             ('12345O789', .99), ('123456789', .75)])
def test_boxed_tin_does_not_guess_missing_or_uncertain_digits(text, confidence):
    reader = Mock(return_value=[row(text, confidence=confidence)])
    output = recover_form_fields(np.zeros((500, 1100, 3), np.uint8), w9_rows(), reader)
    assert 'taxpayer_id' not in extract_structured_document(output).fields


def test_non_w9_does_not_trigger_tin_crop():
    reader = Mock()
    regions = [row('Social security number')]
    assert recover_form_fields(np.zeros((500, 1100, 3), np.uint8), regions, reader) is regions
    reader.assert_not_called()


def test_w9_blank_business_name_does_not_borrow_next_section_instructions():
    regions = w9_rows() + [
        row('Business name/disregarded entity name, if different from above.', y=300),
        row('3a Check the appropriate box', y=340),
        row('only one of the following seven boxes.', y=365)]
    result = extract_structured_document(regions)
    assert 'business_name' not in result.fields


def test_card_fields_ignore_large_specimen_watermark_and_split_sex_date():
    regions = [row('UNITED STATES PASSPORT CARD'),
               row('Passport Card\'no.', x=600, y=40), row('C12345678', x=600, y=70),
               row('Surname', y=110, width=150), row('EXEMPLAR', x=200, y=85, height=80),
               row('EXAMPLE', y=145), row('Given Names', y=180), row('PERSON', y=215),
               row('Sex', x=400, y=250, width=50), row('Date of Birth', x=480, y=250, width=170),
               row('M2 FEB1980', x=400, y=270, width=250),
               row('Expires On', y=320), row('29 NOV2019', y=350)]
    result = extract_structured_document(regions)
    assert result.complete
    assert result.fields['surname'] == 'EXAMPLE'
    assert result.fields['date_of_birth'] == '1980-02-02'
    assert result.fields['expiry_date'] == '2019-11-29'
    assert result.fields['sex'] == 'M'


def test_compact_card_resolution_is_bounded_and_blur_still_rejects():
    _check_resolution(np.zeros((487, 795, 3), np.uint8))
    _check_resolution(np.zeros((600, 600, 3), np.uint8))
    for height, width in [(449, 795), (487, 749), (300, 400)]:
        with pytest.raises(ImageQualityError, match='RESOLUTION_TOO_LOW'):
            _check_resolution(np.zeros((height, width, 3), np.uint8))
    with pytest.raises(ImageQualityError, match='IMAGE_TOO_BLURRY'):
        _check_blur(np.zeros((487, 795, 3), np.uint8))


def test_numbered_us_licence_fields_and_country_state_marker():
    regions = [row('USA SD DRIVER LICENSE'), row('1 EXAMPLE', y=50), row('2 PERSON', y=90),
               row('4d LIC. NO 12345678', y=130), row('3 DOB 01/02/1990', y=170),
               row('4a ISS 07/06/2024', y=210), row('4b EXP 07/06/2029', y=250)]
    result = extract_structured_document(regions)
    assert result.complete
    assert result.fields['document_number'] == '12345678'
    assert result.fields['surname'] == 'EXAMPLE'
    assert result.fields['issue_date'] == '2024-07-06'


@pytest.mark.parametrize('second,accepted', [('123 45 6789', True), ('123 45 6780', False)])
def test_uncertain_boxed_tin_requires_agreement_after_line_removal(second, accepted):
    # One label avoids a second, unrelated TIN box in this confirmation test.
    regions = w9_rows()[:-1]
    reader = Mock(side_effect=[[row('123 45 6789', confidence=.85)], [row(second, confidence=.86)]])
    image = np.zeros((500, 1100, 3), np.uint8)
    result = extract_structured_document(recover_form_fields(image, regions, reader))
    assert ('taxpayer_id' in result.fields) is accepted
    assert reader.call_count == 2
    assert image.max() == 0


def test_identity_field_geometry_follows_tilted_labels():
    import math
    regions = [row('UNITED STATES PASSPORT CARD'),
               row('Surname', y=80, width=140), row('EXAMPLE', y=115, width=180),
               row('Given Names', y=155, width=180), row('PERSON', y=190, width=180),
               row('Passport Card no. C12345678', y=230),
               row('Date of Birth', y=280), row('02 FEB 1980', y=315),
               row('Expires On', y=365), row('29 NOV 2019', y=400)]
    angle = math.radians(35)
    for r in regions:
        r.bbox = [[round(400+x*math.cos(angle)-y*math.sin(angle)),
                   round(100+x*math.sin(angle)+y*math.cos(angle))] for x, y in r.bbox]
    result = extract_structured_document(regions)
    assert result.complete
    assert result.fields['surname'] == 'EXAMPLE'
    assert result.fields['given_names'] == 'PERSON'
    assert result.fields['expiry_date'] == '2019-11-29'


def test_person_names_cannot_be_dates_borrowed_from_nearby_fields():
    result = extract_structured_document([row('UNITED STATES PASSPORT CARD'),
                                         row('Surname', y=60), row('1 JAN 1981', y=95)])
    assert 'surname' not in result.fields
