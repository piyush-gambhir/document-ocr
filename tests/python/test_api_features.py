"""HTTP contracts for hints, batch ordering, capabilities, and durable jobs."""
import asyncio

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

import deploy.docker.server as server
from core.pipeline import DocumentScanResult


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server,'API_TOKEN','test-token')
    monkeypatch.setattr(server,'_ocr_semaphore',asyncio.Semaphore(1))
    async with AsyncClient(transport=ASGITransport(app=server.app),base_url='http://test',headers={'Authorization':'Bearer test-token'}) as client:
        yield client


async def test_scan_passes_normalized_hints_and_evidence(client,monkeypatch):
    seen=[]
    def scan(data,**options):
        seen.append((data,options))
        return DocumentScanResult('success','us_state_id','us_state_id',0.95,document_fields={'document_number':'D123'})
    monkeypatch.setattr(server,'scan',scan)
    response=await client.post('/scan',files={'image':('id.png',b'image','image/png')},
                               data={'document_type':'state-id','country':'USA','include_evidence':'true'})
    assert response.status_code==200
    assert response.json()['documentFields']=={'documentNumber':'D123'}
    assert seen==[(b'image',{'document_type':'us_state_id','country':'US','include_evidence':True})]
    invalid=await client.post('/scan',files={'image':('id.png',b'image','image/png')},data={'document_type':'pan','country':'US'})
    assert invalid.status_code==400
    assert len(seen)==1


async def test_batch_contract_keeps_input_order(client,monkeypatch):
    def batch(images,**options):
        assert images==[b'first',b'second']
        return {'status':'partial','results':[{'status':'success'},{'status':'failure'}],'errors':[]}
    monkeypatch.setattr(server,'scan_batch',batch)
    response=await client.post('/scan/batch',files=[('images',('a.png',b'first','image/png')),('images',('b.png',b'second','image/png'))])
    assert response.status_code==200
    assert response.json()['status']=='partial'


async def test_jobs_auth_persistence_deletion_and_disabled_capability(client,monkeypatch,tmp_path):
    monkeypatch.delenv('DOCUMENT_OCR_JOBS_DIR',raising=False)
    assert (await client.get('/documents')).json()['capabilities']['jobs'] is False
    files=[('images',('id.png',b'private image','image/png'))]
    assert (await client.post('/jobs',files=files)).status_code==503
    monkeypatch.setenv('DOCUMENT_OCR_JOBS_DIR',str(tmp_path))
    monkeypatch.setenv('DOCUMENT_OCR_JOB_KEY',Fernet.generate_key().decode())
    queued=await client.post('/jobs',files=files,data={'country':'US','include_evidence':'true'})
    assert queued.status_code==202
    identifier=queued.json()['id']
    assert 'private image' not in queued.text
    assert (await client.get('/jobs/'+identifier,headers={'Authorization':'wrong'})).status_code==401
    store=server._job_store()
    store.run_once(lambda images,**options:{'status':'success','results':[],'errors':[]})
    assert (await client.get('/jobs/'+identifier)).json()['status']=='succeeded'
    assert (await client.delete('/jobs/'+identifier)).json()=={'deleted':True}
    assert (await client.get('/jobs/'+identifier)).status_code==404


async def test_review_and_preview_have_no_store_policy(client,monkeypatch):
    response=await client.get('/review')
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert 'Export CSV' in response.text
    monkeypatch.setattr(server,'render_preview',lambda data:b'PNG')
    response=await client.post('/preview',files={'image':('id.png',b'image','image/png')})
    assert response.content==b'PNG'
    assert response.headers['Cache-Control']=='no-store'
