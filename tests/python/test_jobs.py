"""Durable queue restart, concurrency, lease, deletion and privacy boundaries."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from cryptography.fernet import Fernet

from core.jobs import JobStore


def test_encrypted_job_survives_restart_and_result_replaces_input(tmp_path):
    key=Fernet.generate_key().decode()
    store=JobStore(tmp_path,key)
    job=store.enqueue([b'SENSITIVE_IMAGE'],{'country':'US'})
    assert b'SENSITIVE_IMAGE' not in store.path.read_bytes()
    restarted=JobStore(tmp_path,key)
    captured=[]
    def process(images,**options):
        captured.append((images,options))
        return {'status':'success','documentFields':{'name':'SENSITIVE_RESULT'}}
    assert restarted.run_once(process)
    assert captured == [([b'SENSITIVE_IMAGE'],{'country':'US'})]
    result=store.get(job['id'])
    assert result['status']=='succeeded'
    assert result['result']['documentFields']['name']=='SENSITIVE_RESULT'
    with store.connection() as db:
        assert db.execute('SELECT payload FROM jobs').fetchone()[0] == b''
    assert b'SENSITIVE_RESULT' not in store.path.read_bytes()


def test_workers_claim_once_and_stale_worker_cannot_overwrite(tmp_path):
    store=JobStore(tmp_path,Fernet.generate_key().decode())
    job=store.enqueue([b'image'],{})
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims=list(pool.map(lambda _:store.claim(),range(4)))
    assert len([c for c in claims if c])==1
    identifier,old_token,_=next(c for c in claims if c)
    with store.connection() as db:
        db.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(identifier,))
    _,new_token,_=store.claim()
    store.finish(identifier,old_token,{'wrong':True})
    assert store.get(identifier)['status']=='running'
    store.finish(identifier,new_token,{'right':True})
    assert store.get(identifier)['result']=={'right':True}


def test_delete_and_expiry_prevent_late_result_resurrection(tmp_path):
    store=JobStore(tmp_path,Fernet.generate_key().decode())
    job=store.enqueue([b'image'],{})
    identifier,token,_=store.claim()
    assert store.delete(identifier)
    store.finish(identifier,token,{'private':True})
    assert store.get(identifier) is None
    job=store.enqueue([b'image'],{})
    with store.connection() as db:
        db.execute('UPDATE jobs SET expires=0')
    assert store.get(job['id']) is None
    assert store.claim() is None


def test_webhook_is_signed_metadata_only_and_retry_persists(tmp_path,monkeypatch):
    monkeypatch.setenv('DOCUMENT_OCR_WEBHOOK_URL','https://receiver.example/ocr')
    monkeypatch.setenv('DOCUMENT_OCR_WEBHOOK_SECRET','s'*32)
    store=JobStore(tmp_path,Fernet.generate_key().decode())
    job=store.enqueue([b'image'],{},notify=True)
    store.run_once(lambda *_a,**_k:{'secret':'PRIVATE_RESULT'})
    requests=[]
    def send(url,**kwargs):
        requests.append((url,kwargs))
        return SimpleNamespace(status_code=503 if len(requests)==1 else 200)
    assert store.deliver_notification(send)
    assert not store.deliver_notification(send)
    with store.connection() as db:
        db.execute('UPDATE jobs SET notify_after=0')
    assert store.deliver_notification(send)
    assert not store.deliver_notification(send)
    import hashlib,hmac
    request=requests[0][1]
    timestamp=request['headers']['X-Document-OCR-Timestamp']
    signature=hmac.new(b's'*32,timestamp.encode()+b'.'+request['data'],hashlib.sha256).hexdigest()
    assert request['headers']['X-Document-OCR-Signature']=='sha256='+signature
    assert json.loads(request['data'])=={'id':job['id'],'status':'succeeded'}
    assert b'PRIVATE_RESULT' not in request['data']
    assert request['allow_redirects'] is False
