"""Merged OCR rows retain labels and values without borrowing adjacent fields."""
import pytest

from core.driving_licence_extractor import extract_driving_licence
from core.pan_extractor import extract_pan
from core.validator import find_label_value
from core.voter_id_extractor import extract_voter_id
from document_samples import regions


def test_pan_inline_person_and_parent_remain_distinct():
    rows = regions('INCOME TAX DEPARTMENT', 'PAN: ABCPA1234F',
        'Name: ANNA SAMPLE', "Father's Name: MOHAN SAMPLE", 'Date of Birth: 15/03/1990')
    rows[2].confidence = .95
    rows[3].confidence = .99
    result = extract_pan(rows)
    assert result.name == 'ANNA SAMPLE'
    assert result.father_name == 'MOHAN SAMPLE'
    assert result.date_of_birth == '15/03/1990'


def test_merged_dl_and_voter_demographics_do_not_require_a_second_text_box():
    licence = extract_driving_licence(regions('DRIVING LICENCE', 'Name: DEV ARUN', 'Blood Group: B+'))
    assert licence.name == 'DEV ARUN'
    assert licence.blood_group == 'B+'
    voter = extract_voter_id(regions('ELECTION COMMISSION OF INDIA', "Elector's Name: DEV ARUN",
        "Mother's Name: ASHA ARUN", 'Sex: FEMALE', 'Date of Birth: 01/12/1992'))
    assert voter.name == 'DEV ARUN'
    assert voter.relation_name == 'ASHA ARUN'
    assert voter.relation_type == 'mother'
    assert voter.gender == 'FEMALE'
    assert voter.date_of_birth == '01/12/1992'


@pytest.mark.parametrize('label', ['Name of the Cardholder', "Father's Name"])
def test_empty_long_label_does_not_become_its_own_value(label):
    assert find_label_value(regions(label), ['NAME', 'NAME OF THE CARDHOLDER', 'FATHER S NAME']) is None


def test_inline_values_preserve_meaningful_punctuation():
    assert find_label_value(regions("Name: ANNE-MARIE O'NEIL"), ['NAME']) == "ANNE-MARIE O'NEIL"


def test_deployed_english_only_config_reuses_one_read_for_known_kyc(monkeypatch):
    import time
    import numpy as np
    from core import pipeline
    from core.preprocessor import PreprocessResult
    rows = regions('INCOME TAX DEPARTMENT', 'Permanent Account Number: ABCPA1234F',
                   'Name: ANNA SAMPLE', 'Date of Birth: 15/03/1990')
    calls = []
    monkeypatch.setenv('DOCUMENT_OCR_KYC_LANGS', 'en')
    def read(_):
        calls.append(True)
        return rows
    monkeypatch.setattr(pipeline, 'run_kyc_ocr', read)
    monkeypatch.setattr(pipeline, 'run_ocr', lambda *_: pytest.fail('duplicate read'))
    result = pipeline._scan_prepared(PreprocessResult(np.zeros((1000, 1600, 3), dtype=np.uint8)), time.monotonic())
    assert result.status == 'success'
    assert result.pan_fields.name == 'ANNA SAMPLE'
    assert len(calls) == 1


@pytest.mark.parametrize('languages', ['', 'en'])
def test_sparse_text_does_not_repeat_an_identical_full_english_read(monkeypatch, languages):
    import time
    import numpy as np
    from core import pipeline
    from core.preprocessor import PreprocessResult
    image = np.zeros((1000, 1600, 3), dtype=np.uint8)
    calls = []
    monkeypatch.setenv('DOCUMENT_OCR_KYC_LANGS', languages)
    def read(pixels, **kwargs):
        if pixels is image:
            calls.append(True)
        return []
    monkeypatch.setattr(pipeline, 'run_ocr', read)
    monkeypatch.setattr(pipeline, 'run_kyc_ocr', read)
    result = pipeline._scan_prepared(PreprocessResult(image), time.monotonic())
    assert result.status == 'failure'
    assert 'NO_TEXT_DETECTED' in result.errors
    assert len(calls) == 1
