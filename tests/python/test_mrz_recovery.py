from unittest.mock import Mock

import numpy as np

from core.mrz_parser import parse_mrz
from core.mrz_recovery import recover_passport_mrz
from core.ocr_engine import TextRegion

LINE1 = 'P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<'
LINE2 = 'L898902C36UTO7408122F1204159ZE184226B<<<<<10'


def region(text, y=300):
    return TextRegion(text, [[10, y], [810, y], [810, y+30], [10, y+30]], .99)


def test_valid_mrz_does_not_trigger_extra_inference():
    rs = [region(LINE1, 260), region(LINE2)]
    ocr = Mock()
    assert recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), rs, ocr) is rs
    ocr.assert_not_called()


def test_recovers_padded_header_from_pixels_and_preserves_visual_coordinates():
    anchor = region(LINE2)
    visual = region('DATE OF BIRTH', 100)
    read = region(LINE1[:-8], 30)
    ocr = Mock(return_value=[read])
    recovered = recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), [visual, anchor], ocr)
    parsed = parse_mrz(recovered)
    assert parsed and parsed.overall_checksum_valid
    assert parsed.raw_lines == (LINE1, LINE2)
    assert recovered[0] is visual
    assert recovered[-1] is anchor
    assert 220 < recovered[1].bbox[0][1] < 300  # Back in original page coordinates.
    ocr.assert_called_once()


def test_bad_checksum_cannot_be_promoted_to_valid():
    bad = region(LINE2[:-1] + '9')
    rs = [bad]
    recovered = recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), rs,
                                     Mock(return_value=[region(LINE1, 30), region(bad.text, 70)]))
    assert recovered is rs


def test_no_mrz_evidence_means_no_extra_ocr():
    rs = [region('Invoice 12345678901234567890')]
    ocr = Mock()
    assert recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), rs, ocr) is rs
    ocr.assert_not_called()


def test_retry_budget_is_bounded_even_with_many_candidates():
    rs = [region(LINE2, y) for y in (100, 180, 260, 340)]
    ocr = Mock(return_value=[])
    assert recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), rs, ocr) is rs
    assert ocr.call_count == 2


def test_degenerate_geometry_does_not_invoke_ocr():
    bad = TextRegion(LINE2, [[0, 0]] * 4, .99)
    ocr = Mock()
    assert recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), [bad], ocr) == [bad]
    ocr.assert_not_called()


def test_passport_number_starting_with_p_is_still_a_line_two_anchor():
    # This is an anchor-selection test, not a valid-identifier fixture.
    anchor = region('P' + LINE2[1:])
    ocr = Mock(return_value=[])
    recover_passport_mrz(np.zeros((500, 900, 3), np.uint8), [anchor], ocr)
    ocr.assert_called_once()
