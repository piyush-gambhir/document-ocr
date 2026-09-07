"""PDF OCR may change contrast, but never the evidence coordinate plane."""
import numpy as np
import pytest

import core.pipeline as pipeline
from core.document_bundle import scan_document
from core.document_input import pdf_pages
from core.preprocessor import PreprocessResult, enhance_contrast
from test_document_features import W9_LINES, make_pdf


def test_pdf_contrast_preserves_pixels_geometry_and_original_view():
    # PDFium rounding can render 1601 pixels: regular image normalization would
    # resize this, invalidating native-text and redaction coordinates.
    original = np.random.default_rng(17).integers(40, 180, (101, 1601, 3), dtype=np.uint8)
    saved = original.copy()
    prep = pipeline._prepare_pdf_ocr(PreprocessResult(original, ['page warning']))
    assert prep.image.shape == original.shape
    np.testing.assert_array_equal(prep.image, enhance_contrast(saved))
    np.testing.assert_array_equal(original, saved)
    assert prep.unenhanced_image is original
    assert prep.warnings == ['page warning']


@pytest.mark.parametrize('grouped', [False, True])
@pytest.mark.parametrize('native_text', [False, True])
def test_pdf_enhances_only_when_visible_ocr_is_needed(monkeypatch, grouped, native_text):
    # Cover the raster path and an unrecognized stale native layer, in both APIs.
    data = make_pdf(['Unrelated scanner text without a document title'] if native_text else [])
    rendered = pdf_pages(data)[0].image
    visible_regions = pdf_pages(make_pdf(W9_LINES))[0].regions
    expected = enhance_contrast(rendered)
    calls = []

    def ocr(image):
        np.testing.assert_array_equal(image, expected)
        calls.append(image)
        return visible_regions

    monkeypatch.setattr(pipeline, 'run_kyc_ocr', ocr)
    monkeypatch.setattr(pipeline, 'run_ocr', lambda _: pytest.fail('complete form needs one read'))
    monkeypatch.setattr(pipeline, 'run_line_ocr', lambda _: pytest.fail('complete form needs no reread'))
    if grouped:
        result = scan_document([data], document_type='us_w9', include_evidence=True)['results'][0]
    else:
        result = pipeline.scan(data, document_type='us_w9', include_evidence=True).to_dict()
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['documentFields']['taxpayerId'] == '123456789'
    assert result['imageSize'] == [rendered.shape[1], rendered.shape[0]]
    assert result['fieldEvidence']['name'][0]['source'] == 'ocr'
    np.testing.assert_array_equal(pipeline.preview_image(data), rendered)


@pytest.mark.parametrize('grouped', [False, True])
def test_recognized_native_pdf_never_enhances_or_offers_an_ocr_alternate(monkeypatch, grouped):
    def unexpected(*_args, **_kwargs):
        pytest.fail('recognized native PDF must remain on the native text path')

    for name in ('enhance_contrast', 'run_ocr', 'run_kyc_ocr', 'run_line_ocr', 'recover_ead_fields'):
        monkeypatch.setattr(pipeline, name, unexpected)
    data = make_pdf(W9_LINES)
    if grouped:
        result = scan_document([data], document_type='us_w9', include_evidence=True)['results'][0]
    else:
        result = pipeline.scan(data, document_type='us_w9', include_evidence=True).to_dict()
    assert result['status'] == 'success'
    assert result['fieldEvidence']['name'][0]['source'] == 'pdf_text'
