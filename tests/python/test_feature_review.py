"""Independent regressions for deadlines, encrypted storage, and PDF redaction."""
import asyncio
import threading
import time

import cv2
import numpy as np
import pytest
from cryptography.fernet import Fernet, InvalidToken

import deploy.docker.server as server
from core.document_input import pdf_pages
from core.jobs import JobStore
from core.redaction import redact
from test_document_features import make_pdf, W9_LINES


async def test_busy_ocr_queue_obeys_request_deadline(monkeypatch):
    semaphore = asyncio.Semaphore(0)
    monkeypatch.setattr(server, '_ocr_semaphore', semaphore)
    monkeypatch.setattr(server, 'SCAN_TIMEOUT_SECONDS', 0.01)
    called = []
    response = await asyncio.wait_for(server._execute(lambda: called.append(True)), 0.2)
    assert response.status_code == 504
    assert not called
    assert semaphore.locked(), 'A queue timeout must not release someone else’s OCR slot'


def test_wrong_job_key_cannot_destroy_pending_work(tmp_path):
    key = Fernet.generate_key().decode()
    original = JobStore(tmp_path, key)
    job = original.enqueue([b'private image'], {})
    with pytest.raises((ValueError, InvalidToken)):
        wrong = JobStore(tmp_path, Fernet.generate_key().decode())
        wrong.run_once(lambda *_args, **_kwargs: {'status': 'success'})
    assert original.get(job['id'])['status'] == 'queued'
    with original.connection() as db:
        assert db.execute('SELECT length(payload) FROM jobs').fetchone()[0] > 0
    assert original.run_once(lambda *_args, **_kwargs: {'status': 'success'})
    assert original.get(job['id'])['status'] == 'succeeded'


async def test_sqlite_writer_does_not_block_http_health(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode()
    store = JobStore(tmp_path, key)
    monkeypatch.setenv('DOCUMENT_OCR_JOBS_DIR', str(tmp_path))
    monkeypatch.setenv('DOCUMENT_OCR_JOB_KEY', key)
    monkeypatch.setattr(server, 'API_TOKEN', None)
    locked, release = threading.Event(), threading.Event()

    def write_transaction():
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            locked.set()
            # The timeout keeps the regression finite if HTTP blocks the loop.
            release.wait(0.6)

    writer = threading.Thread(target=write_transaction)
    writer.start()
    assert locked.wait(1)
    started = time.monotonic()
    capabilities = asyncio.create_task(server.documents())
    try:
        await asyncio.sleep(0.02)
        assert await server.health() == {'status': 'ok'}
        assert time.monotonic() - started < 0.25, 'SQLite locks must not stall unrelated HTTP requests'
    finally:
        release.set()
        await asyncio.to_thread(writer.join)
        result = await capabilities
    assert result['capabilities']['jobs'] is True


def test_cropped_pdf_evidence_redacts_actual_ink_or_defers_to_ocr():
    data = make_pdf(W9_LINES).replace(
        b'/MediaBox [0 0 612 792]',
        b'/MediaBox [0 0 612 792] /CropBox [20 20 592 772]',
    )
    page = pdf_pages(data)[0]
    if not page.regions:
        # Falling back to rendered OCR is safe when the PDF transform is unknown.
        return
    region = next(region for region in page.regions if 'JANE SAMPLE' in region.text)
    output = cv2.imdecode(np.frombuffer(redact(data, [region.bbox]), np.uint8), cv2.IMREAD_COLOR)
    # The fixture's name is the third line. Its visible ink lies here after the
    # crop translation, independently of the extracted PDF character geometry.
    original_line = page.image[190:250, 40:600]
    redacted_line = output[190:250, 40:600]
    ink = np.any(original_line < 100, axis=2)
    assert ink.sum() > 100
    assert np.all(redacted_line[ink] == 0), 'Returned evidence must cover the visible private text'
