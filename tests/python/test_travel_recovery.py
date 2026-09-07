from unittest.mock import Mock

import numpy as np
import pytest

from core.mrz_parser import _clean_mrz_text, icao_check_digit, parse_mrz
from core.document_registry import MRZ_COUNTRY_CODES, is_known_mrz_country
from core.ocr_engine import TextRegion
from core.travel_mrz import parse_travel_mrz
from core.travel_recovery import recover_travel_mrz
from core.validator import validate
from document_samples import td1_lines, visa_lines


PASSPORT = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
IMAGE = np.zeros((600, 1000, 3), np.uint8)


def row(text, y=300, confidence=.99):
    return TextRegion(text, [[30, y], [930, y - 10], [930, y + 25], [30, y + 35]], confidence)


def pair(lines):
    return [row(lines[0], 300), row(lines[1], 360)]


def reread(text, confidence=.99):
    return [TextRegion(text, [[0, 0], [899, 0], [899, 40], [0, 40]], confidence)]


def test_unicode_compatibility_glyphs_are_normalized_without_guessing_country():
    assert _clean_mrz_text("P<ⅠNDＳＡＭＰＬＥ<<ANNA<MARⅠA") == "P<INDSAMPLE<<ANNA<MARIA"
    assert _clean_mrz_text("P<|ND") == "P<|ND"
    assert _clean_mrz_text("P<ІND") == "P<ІND"  # Cyrillic I is not a compatibility equivalent.


def test_shared_country_codes_include_iso_territories_and_icao_exceptions():
    for code in ("ABW", "ALA", "D<<", "GBN", "XXA", "UNO", "UTO", "IND",
                 "RKS", "UNK", "XCE", "XCO", "XEC", "XPO", "XES", "XMP", "XDC", "XXX", "ANT", "NTZ"):
        assert is_known_mrz_country(code)
    for code in ("LND", "TND", "IAO", "", "<", None):
        assert not is_known_mrz_country(code)
    assert isinstance(MRZ_COUNTRY_CODES, frozenset)


def test_unchecked_unknown_nationality_is_rejected_even_when_checksums_pass():
    first, second = visa_lines(36)
    rows = pair([first, second[:10] + "LND" + second[13:]])
    result = parse_travel_mrz(rows)
    assert result.checks["mrz_checksums_valid"]
    assert "UNKNOWN_NATIONALITY" in result.errors


def test_roman_numeral_i_in_passport_name_does_not_trigger_recovery():
    lines = [PASSPORT[0].replace("I", "Ⅰ"), PASSPORT[1]]
    rows = pair(lines)
    reader = Mock()
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    assert parse_mrz(rows).given_names.value == "ANNA MARIA"
    reader.assert_not_called()


@pytest.mark.parametrize("kind", ["visa", "passport_card"])
def test_shared_unicode_normalization_applies_to_other_travel_mrz(kind):
    lines = visa_lines() if kind == "visa" else td1_lines()
    rows = [row(line.replace("I", "Ⅰ"), 150 + index * 60) for index, line in enumerate(lines)]
    result = parse_travel_mrz(rows)
    assert result.document_type == kind
    assert result.fields["given_names"] == "ANNA MARIA"
    assert result.checks["mrz_checksums_valid"]


@pytest.mark.parametrize("lines", [PASSPORT, visa_lines(36), visa_lines(44)])
def test_valid_complete_mrz_has_zero_extra_inference(lines):
    rows = pair(lines)
    reader = Mock()
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    reader.assert_not_called()


@pytest.mark.parametrize("lines", [PASSPORT, visa_lines(36), visa_lines(44)])
def test_unspecified_nationality_is_valid_and_does_not_trigger_ocr(lines):
    first, second = lines
    second = second[:10] + "XXX" + second[13:]
    rows = pair([first, second])
    reader = Mock()
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    reader.assert_not_called()
    if first.startswith('P'):
        parsed = parse_mrz(rows)
        assert parsed.overall_checksum_valid and parsed.nationality.value == 'XXX'
        assert validate(parsed, rows).errors == []
    else:
        parsed = parse_travel_mrz(rows)
        assert parsed.checks['mrz_checksums_valid']
        assert parsed.fields['nationality'] == 'XXX' and parsed.errors == []


@pytest.mark.parametrize('issuer', ['RKS', 'UNK', 'XPO', 'ANT'])
def test_standard_special_issuers_are_not_rejected_or_reread_in_passports(issuer):
    rows = pair([PASSPORT[0][:2] + issuer + PASSPORT[0][5:], PASSPORT[1]])
    reader = Mock()
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    assert validate(parse_mrz(rows), rows).errors == []
    reader.assert_not_called()


def test_agreeing_pixels_recover_only_unknown_nationality_and_map_evidence():
    first, second = visa_lines(36)
    damaged = second[:10] + "LND" + second[13:]
    rows = pair([first, damaged])
    visual = row("Surname: SAMPLE", 100)
    rows.insert(0, visual)
    reader = Mock(side_effect=[reread(second, .84), reread(second, .98)])
    result = recover_travel_mrz(IMAGE, rows, reader)
    assert result[0] is visual and result[1] is rows[1]
    parsed = parse_travel_mrz(result)
    assert parsed.fields["nationality"] == "USA"
    assert parsed.fields["document_number"] == "L898902C3"
    assert parsed.checks["mrz_checksums_valid"]
    assert result[-1].confidence == .84
    assert 330 < result[-1].bbox[0][1] < 390
    assert reader.call_count == 2


def test_unknown_issuer_requires_agreement_and_preserves_name():
    lines = PASSPORT.copy()
    lines[0] = "P<|TO" + lines[0][5:]
    rows = pair(lines)
    reader = Mock(return_value=reread(PASSPORT[0]))
    result = recover_travel_mrz(IMAGE, rows, reader)
    assert parse_mrz(result).country_code.value == "UTO"
    assert result[-1] is rows[-1]
    assert reader.call_count == 2


@pytest.mark.parametrize("failure", ["disagree", "low_confidence", "bad_checksum", "changed_number", "unknown_country"])
def test_uncertain_or_conflicting_rereads_are_not_admitted(failure):
    first, second = visa_lines(36)
    rows = pair([first, second[:10] + "LND" + second[13:]])
    candidate = second
    if failure == "bad_checksum":
        candidate = candidate[:9] + "0" + candidate[10:]
    elif failure == "changed_number":
        number = "A12345678"
        candidate = number + str(icao_check_digit(number)) + candidate[10:]
    elif failure == "unknown_country":
        candidate = candidate[:10] + "ZZZ" + candidate[13:]
    first_read = reread(candidate, .75 if failure == "low_confidence" else .99)
    second_read = reread(candidate if failure != "disagree" else second[:10] + "CAN" + second[13:])
    reader = Mock(side_effect=[first_read, second_read])
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    assert reader.call_count == 2


def test_issuer_recovery_does_not_replace_an_existing_name():
    damaged = "P<|TO" + PASSPORT[0][5:]
    rows = pair([damaged, PASSPORT[1]])
    changed_name = PASSPORT[0].replace("MARIA", "MARTA")
    reader = Mock(return_value=reread(changed_name))
    assert recover_travel_mrz(IMAGE, rows, reader) is rows


def test_recovering_a_truncated_header_cannot_change_a_plausible_issuer():
    first, second = visa_lines(36)
    rows = pair([first[:-3], second])
    changed_issuer = first[:2] + "CAN" + first[5:]
    reader = Mock(return_value=reread(changed_issuer))
    assert recover_travel_mrz(IMAGE, rows, reader) is rows


def test_incomplete_visa_header_is_reread_without_inventing_fillers():
    first, second = visa_lines(36)
    rows = pair([first[:-3], second])
    reader = Mock(return_value=reread(first))
    result = recover_travel_mrz(IMAGE, rows, reader)
    assert parse_travel_mrz(result).fields["mrz_raw"] == [first, second]
    assert reader.call_count == 2


def test_multiple_candidate_documents_and_unrelated_text_do_not_trigger_reread():
    first, second = visa_lines(36)
    damaged = first[:2] + "LND" + first[5:]
    duplicate = pair([damaged, second]) + [row(damaged, 440), row(second, 500)]
    unrelated = [row("INVOICE TOTAL 12345678901234567890", 100)]
    for rows in (duplicate, unrelated):
        reader = Mock()
        assert recover_travel_mrz(IMAGE, rows, reader) is rows
        reader.assert_not_called()


def test_implausible_geometry_does_not_allocate_or_read_crop():
    first, second = visa_lines(36)
    rows = pair([first[:2] + "LND" + first[5:], second])
    rows[0].bbox = [[0, 0]] * 4
    reader = Mock()
    assert recover_travel_mrz(IMAGE, rows, reader) is rows
    reader.assert_not_called()
