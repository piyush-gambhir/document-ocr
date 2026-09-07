"""Integration coverage for native PDFs, grouped records, evidence and redaction."""
import io
import json

import cv2
import numpy as np
import pytest

from core.document_input import pdf_pages
from core.document_bundle import reconcile_pages, scan_document
from core.pipeline import scan
from core.redaction import redact
from core.preprocessor import ImageQualityError


def make_pdf(lines, *, pages=1, width=612, height=792):
    # A real, minimal PDF with a native text layer. No OCR/parsing stubs.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for _ in range(pages):
        page_no = len(objects)+1
        kids.append(f'{page_no} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_no+1} 0 R >>'.encode())
        commands = ['BT /F1 16 Tf 40 740 Td 26 TL']
        for index, line in enumerate(lines):
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(('T* ' if index else '') + f'({escaped}) Tj')
        commands.append('ET')
        stream = '\n'.join(commands).encode()
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {pages} >>'.encode()
    data=b'%PDF-1.4\n';offsets=[0]
    for index, obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{index} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data)
    data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data+=b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    data+=f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()
    return data


W9_LINES = ['Form W-9', 'Request for Taxpayer Identification Number and Certification',
            'Name: JANE SAMPLE', 'Employer identification number: 12-3456789']


def test_native_pdf_extracts_fields_without_ocr(monkeypatch):
    import core.pipeline as pipeline
    monkeypatch.setattr(pipeline, 'run_kyc_ocr', lambda _: pytest.fail('native form must not need OCR'))
    result = scan(make_pdf(W9_LINES), document_type='us_w9', include_evidence=True).to_dict()
    assert result['status'] == 'success'
    assert result['documentFields']['taxpayerId'] == '123456789'
    assert result['documentFields']['name'] == 'JANE SAMPLE'
    evidence = result['fieldEvidence']['taxpayerId'][0]
    assert evidence['source'] == 'pdf_text'
    assert 0 < evidence['bbox'][0][0] < evidence['bbox'][1][0] < result['imageSize'][0]
    assert 'PDF_NATIVE_TEXT_NOT_VISUALLY_VERIFIED' in result['warnings']


def test_pdf_page_limit_and_single_page_warning():
    data=make_pdf(W9_LINES,pages=2)
    result=scan(data,document_type='us_w9')
    assert 'PDF_ADDITIONAL_PAGES_IGNORED' in result.warnings
    grouped=scan_document([data],document_type='us_w9',include_evidence=True)
    assert len(grouped['results']) == 2
    assert grouped['status'] == 'success'
    assert grouped['results'][1]['fieldEvidence']['name'][0]['page'] == 2
    with pytest.raises(ImageQualityError,match='TOO_MANY_PAGES'):
        pdf_pages(make_pdf(W9_LINES,pages=11))
    with pytest.raises(ImageQualityError,match='PDF_PAGE_TOO_LARGE'):
        pdf_pages(make_pdf([],width=10,height=10000))


def test_grouping_does_not_merge_conflicting_people():
    def result(number):
        return {'status':'success','documentType':'passport', 'issuingCountry':'US',
                'documentFields':{'passportNumber':number,'surname':'DOE'},'fieldEvidence':{}}
    bundle=reconcile_pages([result('A12345678'),result('B12345678')])
    assert bundle['status'] == 'failure'
    assert 'passportNumber' not in bundle['documentFields']
    assert bundle['conflicts'] == [{'field':'passportNumber','values':[
        {'page':1,'value':'A12345678'},{'page':2,'value':'B12345678'}]}]


def test_grouping_rejects_different_document_families():
    results=[{'status':'success','documentType':t,'documentFields':{}} for t in ['pan','passport']]
    assert reconcile_pages(results)['errors'] == ['CONFLICTING_DOCUMENT_PAGES']


def test_redaction_burns_pixels_and_rejects_out_of_bounds(monkeypatch):
    import core.redaction as redaction
    image=np.full((100,200,3),255,dtype=np.uint8)
    monkeypatch.setattr(redaction,'preview_image',lambda _:image)
    data=redact(b'image',[[[20,20],[80,20],[80,40],[20,40]]])
    output=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    assert np.all(output[20:40,20:80] == 0)
    assert np.all(output[80:,150:] == 255)
    assert np.all(image == 255)
    for boxes in [[], [[[0,0],[201,0],[201,30],[0,30]]], [[[0,0],[float('nan'),0],[30,30],[0,30]]]]:
        with pytest.raises(ValueError,match='INVALID_REDACTION_BOXES'):
            redact(b'image',boxes)


def test_unidentified_native_layer_with_hint_falls_back_to_visible_ocr(monkeypatch):
    import core.pipeline as pipeline
    calls = []
    visible_regions = pdf_pages(make_pdf(W9_LINES))[0].regions
    def ocr(image):
        calls.append(image.shape)
        return visible_regions
    monkeypatch.setattr(pipeline, 'run_kyc_ocr', ocr)
    result = scan(make_pdf(['Unrelated old scanner text with no document title']),
                  document_type='us_w9', include_evidence=True).to_dict()
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['documentFields']['taxpayerId'] == '123456789'
    assert result['fieldEvidence']['name'][0]['source'] == 'ocr'
