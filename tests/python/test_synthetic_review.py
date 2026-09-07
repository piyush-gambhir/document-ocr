"""Independent semantic and routing checks; no OCR model inference."""
import time

import numpy as np
import pytest
from PIL import ImageDraw

from benchmarks.synthetic_documents import PROFILES, definition, render
from core import pipeline
from core.preprocessor import PreprocessResult
from document_samples import regions


def checksum(value):
    # Separate implementation using ICAO's decimal character weights.
    values = [0 if char == '<' else ord(char) - 48 if char.isdigit() else ord(char) - 55
              for char in value]
    return str(sum(number * (7, 3, 1)[index % 3]
                   for index, number in enumerate(values)) % 10)


@pytest.mark.parametrize('identity', [0, 1])
def test_synthetic_travel_mrz_truth_agrees_with_visible_values_and_checksums(identity):
    passport = definition('passport', identity)
    first, second = passport['mrzRaw']
    fields = passport['fields']
    assert len(first) == len(second) == 44
    assert first[2:5] == fields['countryCode'] == fields['nationality']
    assert first[5:].split('<<')[0] == fields['surname']
    assert second[:9].rstrip('<') == fields['passportNumber']
    assert second[13:19] == fields['dateOfBirth']
    assert second[21:27] == fields['expiryDate']
    assert second[9] == checksum(second[:9])
    assert second[19] == checksum(second[13:19])
    assert second[27] == checksum(second[21:27])
    assert second[43] == checksum(second[:10] + second[13:20] + second[21:43])
    printed = dict(passport['lines'])
    assert printed['Passport Number'] == fields['passportNumber']
    assert printed['Date of Birth'][6:] + printed['Date of Birth'][3:5] + printed['Date of Birth'][:2] == '19' + fields['dateOfBirth']

    visa = definition('visa', identity)
    first, second = visa['mrzRaw']
    fields = visa['fields']
    assert len(first) == len(second) == (44 if fields['mrzFormat'] == 'MRV_A' else 36)
    assert second[:9] == fields['documentNumber']
    assert second[10:13] == fields['nationality']
    assert second[9] == checksum(second[:9])
    assert second[19] == checksum(second[13:19])
    assert second[27] == checksum(second[21:27])


def test_every_synthetic_value_is_drawn_without_clipping(monkeypatch):
    # Observe the actual drawing calls, so future font/layout changes cannot
    # leave a duplicate test implementation measuring an obsolete layout.
    original_draw = ImageDraw.Draw
    drawn = []

    def tracked_draw(image, *args, **kwargs):
        draw = original_draw(image, *args, **kwargs)
        original_text = draw.text

        def checked_text(position, text, *text_args, **text_kwargs):
            bounds = draw.textbbox(position, text, font=text_kwargs['font'])
            assert 0 <= bounds[0] <= bounds[2] < image.width, text
            assert 0 <= bounds[1] <= bounds[3] < image.height, text
            drawn.append(text)
            return original_text(position, text, *text_args, **text_kwargs)

        draw.text = checked_text
        return draw

    monkeypatch.setattr(ImageDraw, 'Draw', tracked_draw)
    for kind in PROFILES:
        for identity in (0, 1):
            data = definition(kind, identity)
            drawn.clear()
            render(data)
            for label, value in data['lines']:
                text = label + (': ' if label else '') + value
                assert text in drawn, (kind, label)
            assert 'SYNTHETIC OCR TEST - NOT A VALID DOCUMENT' in drawn


@pytest.mark.parametrize('background_title', [
    'NATIONAL POPULATION REGISTER', 'MAHATMA GANDHI NREGA',
])
def test_valid_full_page_mrz_keeps_passport_routing_despite_background_keywords(monkeypatch, background_title):
    # Ancillary/background text is weaker than the already readable valid MRZ.
    # This specifically exercises the new early KYC return, not MRZ recovery.
    data = definition('passport', 0)
    full = regions(*data['title'], background_title, *data['mrzRaw'])
    assert pipeline.parse_mrz(full).overall_checksum_valid
    assert pipeline._is_strong_non_passport_classification(pipeline.classify_document(full))
    monkeypatch.setattr(pipeline, 'run_ocr', lambda *args, **kwargs: full)
    monkeypatch.setattr(pipeline, 'run_line_ocr', lambda *args, **kwargs: pytest.fail('unexpected OCR retry'))
    monkeypatch.setattr('core.kyc_ocr.configured_kyc_languages', lambda: [])
    result = pipeline._scan_prepared(
        PreprocessResult(image=np.zeros((1500, 1200, 3), dtype=np.uint8), warnings=[]),
        time.monotonic(),
    )
    assert result.document_type == 'passport'
    assert result.mrz_valid is True


@pytest.mark.parametrize('document_type,include_evidence', [(None, True), ('passport', False)])
def test_requesting_passport_evidence_or_hint_preserves_valid_mrz_routing(monkeypatch, document_type, include_evidence):
    data = definition('passport', 0)
    full = regions(*data['title'], 'NATIONAL POPULATION REGISTER', *data['mrzRaw'])
    monkeypatch.setattr(pipeline, 'run_kyc_ocr', lambda *args, **kwargs: full)
    monkeypatch.setattr(pipeline, 'run_ocr', lambda *args, **kwargs: full)
    monkeypatch.setattr(pipeline, 'run_line_ocr', lambda *args, **kwargs: pytest.fail('unexpected OCR retry'))
    monkeypatch.setattr(pipeline, 'decode_barcodes', lambda *args, **kwargs: [])
    result = pipeline._scan_page(
        PreprocessResult(image=np.zeros((1500, 1200, 3), dtype=np.uint8), warnings=[]),
        time.monotonic(), document_type, None, include_evidence,
    )
    assert result.document_type == 'passport'
    assert result.mrz_valid is True
