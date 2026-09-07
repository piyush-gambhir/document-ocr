"""Passport orchestration regressions with real parsing and synthetic OCR regions."""

import numpy as np
import pytest

import core.pipeline as pipeline
from core.ocr_engine import TextRegion
from core.preprocessor import PreprocessResult


def region(text, y):
    return TextRegion(text, [[40, y], [740, y], [740, y + 25], [40, y + 25]], 0.99)


def mrz_regions():
    return [
        region('P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<', 800),
        region('L898902C36UTO7408122F1204159ZE184226B<<<<<10', 850),
    ]


@pytest.fixture
def prepare(monkeypatch):
    image = np.zeros((1000, 800, 3), dtype=np.uint8)
    monkeypatch.setattr(pipeline, 'preprocess', lambda _: PreprocessResult(image))

    def install(probe, full):
        calls = []
        monkeypatch.setattr(pipeline, '_extract_targeted_regions', lambda _: probe)

        def read_full(_image, **_kwargs):
            calls.append('full')
            return full

        monkeypatch.setattr(pipeline, 'run_ocr', read_full)
        monkeypatch.setattr(pipeline, 'run_kyc_ocr', read_full)
        return calls

    return install


def test_valid_cropped_mrz_still_extracts_fields_above_crop(prepare):
    full = [region('Place of Birth', 40), region('STOCKHOLM', 75),
            region('Date of Issue', 140), region('15/04/2002', 175), *mrz_regions()]
    calls = prepare(mrz_regions(), full)
    result = pipeline.scan(b'synthetic')
    assert result.status == 'success'
    assert result.mrz_valid
    assert result.fields.place_of_birth == 'STOCKHOLM'
    assert result.fields.issue_date == '15/04/2002'
    assert calls == ['full']


def test_full_page_visual_mismatch_is_not_hidden_by_valid_crop(prepare):
    full = [region('Surname', 40), region('DIFFERENT PERSON', 75), *mrz_regions()]
    prepare(mrz_regions(), full)
    result = pipeline.scan(b'synthetic')
    assert 'NAME_MISMATCH' in result.warnings
    assert result.confidence < 0.8


@pytest.mark.parametrize('probe', [[], [region('Unrelated footer', 950)]])
def test_full_page_passport_recovers_when_crop_misses_it(prepare, probe):
    calls = prepare(probe, mrz_regions())
    result = pipeline.scan(b'synthetic')
    assert result.status == 'success'
    assert result.document_type == 'passport'
    assert result.fields.passport_number == 'L898902C3'
    assert calls == ['full']


def test_valid_crop_survives_failed_full_page_mrz(prepare):
    full = [region('Date of Issue', 40), region('15/04/2002', 75)]
    prepare(mrz_regions(), full)
    result = pipeline.scan(b'synthetic')
    assert result.status == 'success'
    assert result.mrz_valid
    assert result.fields.passport_number == 'L898902C3'
    assert result.fields.issue_date == '15/04/2002'


@pytest.mark.parametrize('full', [[], [region('Name of Father', 50), region('Address', 100)]])
def test_passport_back_without_values_is_not_success(prepare, full):
    prepare([region('Name of Father', 50), region('Address', 100)], full)
    result = pipeline.scan(b'synthetic')
    assert result.status == 'failure'
    assert result.errors == ['NO_BACK_PAGE_FIELDS_DETECTED']
    assert result.confidence == 0


@pytest.mark.parametrize('data', [b'not an image', b'%PDF-invalid'])
def test_invalid_document_is_a_structured_failure(data):
    result = pipeline.scan(data)
    assert result.status == 'failure'
    assert result.document_type == 'unknown'
    assert result.errors == ['INVALID_PDF' if data.startswith(b'%PDF-') else 'INVALID_IMAGE']


@pytest.mark.parametrize('full_is_valid', [True, False])
def test_checksum_valid_mrz_wins_over_competing_reading(prepare, full_is_valid):
    good = mrz_regions()
    bad = [good[0], region(good[1].text[:-1] + '1', 850)]
    prepare(bad if full_is_valid else good, good if full_is_valid else bad)
    result = pipeline.scan(b'synthetic')
    assert result.status == 'success'
    assert result.mrz_valid
    assert result.mrz_raw == tuple(item.text for item in good)


def test_checksum_valid_impossible_date_cannot_be_success(prepare):
    from core.mrz_parser import icao_check_digit

    # Correct check digits alone cannot establish that February has 31 days.
    good = mrz_regions()
    line = list(good[1].text)
    line[13:19] = '740231'
    line[19] = str(icao_check_digit(''.join(line[13:19])))
    line[43] = str(icao_check_digit(''.join(line[:10] + line[13:20] + line[21:43])))
    regions = [good[0], region(''.join(line), 850)]
    prepare(regions, regions)
    result = pipeline.scan(b'synthetic')
    assert result.mrz_valid  # checksums and calendar validity are distinct
    assert result.status == 'failure'
    assert 'INVALID_DATE_OF_BIRTH' in result.errors


@pytest.mark.parametrize('hint', [None, 'passport'])
def test_recovered_high_passport_routes_past_background_text(prepare, monkeypatch, hint):
    first, second = mrz_regions()
    first.bbox = [[40, 183], [740, 183], [740, 213], [40, 213]]
    second.bbox = [[40, 220], [740, 220], [740, 250], [40, 250]]
    background = region('Background writing', 950)
    prepare([background], [second, background])
    # The detector misses the name line even in the recovery band. The
    # recognition-only read returns it in crop coordinates.
    monkeypatch.setattr(pipeline, 'run_ocr', lambda _: [])
    monkeypatch.setattr(pipeline, 'run_line_ocr', lambda _: [
        TextRegion(first.text, [[0, 0], [699, 0], [699, 35], [0, 35]], .97)])
    result = pipeline.scan(b'synthetic', document_type=hint)
    assert result.status == 'success'
    assert result.page_type == 'passport_biodata'
    assert result.mrz_raw == (first.text, second.text)
    assert result.fields.passport_number == 'L898902C3'
