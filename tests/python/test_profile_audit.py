"""Contract regressions exposed by specimen review; no OCR inference required."""
import json
from pathlib import Path

import pytest

from benchmarks.additional_profiles import prepare
from core.structured_documents import extract_structured_document
from document_samples import regions


@pytest.mark.parametrize('title,category', [
    ('PERMANENT RESIDENT', 'IR1'), ('PERMANENT RESIDENT', 'CR1'),
    ('EMPLOYMENT AUTHORIZATION', 'C09'),
])
def test_uscis_visual_category_keeps_both_one_and_two_letter_prefixes(title, category):
    # IR1 is visible on the USCIS 2023 green-card comparison specimen.
    # https://www.uscis.gov/sites/default/files/document/guides/GreenCard_Comparison_EN.PDF.pdf
    result = extract_structured_document(regions(
        f'UNITED STATES {title}',
        'Surname: SPECIMEN', 'USCIS: 123-456-789',
        'Card Number: MSC0123456789', 'Date of Birth: 20 OCT 2002',
        f'Category: {category}',
    ))
    assert result.fields.get('category') == category


def test_historical_ead_printed_two_digit_validity_dates_are_extracted():
    # Exact visible dates from the hash-pinned reviewed USCIS specimen.
    result = extract_structured_document(regions(
        'UNITED STATES EMPLOYMENT AUTHORIZATION',
        'Surname: SPECIMEN', 'Given Name: TEST V', 'USCIS#: 000-000-811',
        'Card#: SRC0000000811', 'Date of Birth: 01 JAN 1920',
        'Valid From: 01/01/80', 'Card Expires: 05/10/11',
    ))
    assert result.fields.get('valid_from') == '1980-01-01'
    assert result.fields.get('expiry_date') == '2011-05-10'
    assert result.complete


def test_i94_year_first_month_dates_and_last_surname_label():
    result = extract_structured_document(regions(
        'Most Recent I-94', 'Admission (I-94) Record Number: 123456789A1',
        'Last/Surname: EXAMPLE', 'First (Given) Name: ANNA',
        'Birth Date: 1990 March 15', 'Most Recent Date of Entry: 2026 August 01',
        'Class of Admission: F1', 'Admit Until Date: 2027 February 01',
    ))
    assert result.fields.get('surname') == 'EXAMPLE'
    assert result.fields.get('date_of_birth') == '1990-03-15'
    assert result.fields.get('admission_date') == '2026-08-01'
    assert result.fields.get('admit_until') == '2027-02-01'
    assert result.complete


@pytest.mark.parametrize('printed', ['06/0 1/2025', ' 06 / 01 / 2025 ', '06- 01-2025'])
def test_numeric_us_date_preserves_digits_when_ocr_inserts_spaces(printed):
    from core.structured_documents import _us_date
    assert _us_date(printed) == '2025-06-01'


@pytest.mark.parametrize('printed', ['06/011/2025', 'O6/01/2025', '06/01/2025 extra', '02/30/2025'])
def test_us_date_never_guesses_missing_digits_or_letters(printed):
    from core.structured_documents import _us_date
    assert _us_date(printed) is None


def test_specimen_preparation_never_fetches_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr('benchmarks.additional_profiles.fetch_bytes',
                        lambda *args: pytest.fail('network fetch was not opted into'))
    with pytest.raises(FileNotFoundError, match='rerun with --fetch'):
        prepare(tmp_path)


def test_specimen_truth_is_pinned_and_matches_the_case():
    base = Path(__file__).resolve().parents[2] / 'benchmarks'
    manifest = json.loads((base / 'additional_profile_samples.json').read_text())
    from benchmarks.public_data import check_bytes
    for record in manifest['files']:
        if record['kind'] == 'generated':
            raw = (base / 'specimen_truth' / record['sourceFile']).read_bytes()
            check_bytes(raw, record)
            truth = json.loads(raw)
            assert truth['documentType'] == manifest['cases'][0]['profile']
            assert truth['fieldBlock'] == manifest['cases'][0]['fieldBlock']
            assert len(truth['fields']) == 10
