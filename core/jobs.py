"""Optional encrypted SQLite queue for a persistent server volume.

Run a separate worker: python -m core.jobs worker. This is deliberately disabled
unless DOCUMENT_OCR_JOBS_DIR and DOCUMENT_OCR_JOB_KEY are configured. Do not put
the database on ephemeral/serverless storage or a network filesystem.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import sqlite3
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

MAX_JOBS = 1000
MAX_ATTEMPTS = 3
LEASE_SECONDS = 3600


class JobStore:
    def __init__(self, directory: str | Path, key: str, *, retention_seconds: int = 86400):
        if not 60 <= retention_seconds <= 604800:
            raise ValueError('INVALID_JOB_RETENTION')
        self.cipher = Fernet(key.encode())
        self.retention = retention_seconds
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'jobs.sqlite3'
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, payload BLOB NOT NULL, result BLOB,
                attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL, lease_token TEXT,
                error TEXT, notify INTEGER NOT NULL DEFAULT 0,
                notification_attempts INTEGER NOT NULL DEFAULT 0,
                notify_after REAL NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0
            )''')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            sentinel = db.execute("SELECT value FROM metadata WHERE key='encryption_key_check'").fetchone()
            try:
                if sentinel is not None:
                    if self.cipher.decrypt(sentinel[0]) != b'document-ocr-jobs-v1':
                        raise ValueError('JOB_KEY_MISMATCH')
                else:
                    # Validate any pre-sentinel queue before migrating it.
                    previous = db.execute("SELECT payload,result FROM jobs WHERE length(payload)>0 OR result IS NOT NULL LIMIT 1").fetchone()
                    if previous is not None:
                        self.cipher.decrypt(previous['payload'] or previous['result'])
                    db.execute("INSERT INTO metadata (key,value) VALUES ('encryption_key_check',?)",
                               (self.cipher.encrypt(b'document-ocr-jobs-v1'),))
            except InvalidToken as exc:
                raise ValueError('JOB_KEY_MISMATCH') from exc
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _encrypt(self, value) -> bytes:
        return self.cipher.encrypt(json.dumps(value, separators=(',', ':')).encode())

    def _decrypt(self, value):
        return json.loads(self.cipher.decrypt(value))

    def enqueue(self, images: list[bytes], options: dict, *, grouped: bool = False, notify: bool = False) -> dict:
        if not 1 <= len(images) <= 10 or sum(map(len, images)) > 10 * 1024 * 1024:
            raise ValueError('INVALID_JOB_SIZE')
        if notify and not webhook_configuration():
            raise ValueError('WEBHOOK_NOT_CONFIGURED')
        payload = self._encrypt({'images': [base64.b64encode(i).decode() for i in images],
                                 'options': options, 'grouped': grouped})
        now, identifier = time.time(), str(uuid.uuid4())
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM jobs WHERE expires <= ?', (now,))
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0] >= MAX_JOBS:
                raise ValueError('JOB_QUEUE_FULL')
            db.execute('INSERT INTO jobs (id,status,created,expires,payload,notify) VALUES (?,?,?,?,?,?)',
                       (identifier, 'queued', now, now + self.retention, payload, int(notify)))
        return self.get(identifier)

    def get(self, identifier: str) -> dict | None:
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND expires>?', (identifier, time.time())).fetchone()
        if row is None:
            return None
        result = {'id': row['id'], 'status': row['status'], 'createdAt': row['created'],
                  'expiresAt': row['expires'], 'attempts': row['attempts'], 'error': row['error']}
        if row['result']:
            result['result'] = self._decrypt(row['result'])
        return result

    def delete(self, identifier: str) -> bool:
        with self.connection() as db:
            return db.execute('DELETE FROM jobs WHERE id=?', (identifier,)).rowcount > 0

    def claim(self):
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM jobs WHERE expires<=?', (now,))
            db.execute("UPDATE jobs SET status='failed',error='WORKER_RETRIES_EXHAUSTED',payload=? WHERE status='running' AND lease_until<=? AND attempts>=?", (b'', now, MAX_ATTEMPTS))
            row = db.execute("SELECT * FROM jobs WHERE (status='queued' OR (status='running' AND lease_until<=?)) AND attempts<? ORDER BY created LIMIT 1", (now, MAX_ATTEMPTS)).fetchone()
            if row is None:
                return None
            token = str(uuid.uuid4())
            db.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_until=?,lease_token=? WHERE id=?", (now+LEASE_SECONDS, token, row['id']))
        return row['id'], token, row['payload']

    def finish(self, identifier: str, token: str, result=None, *, error: str | None = None):
        encrypted = self._encrypt(result) if result is not None else None
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?,result=?,payload=?,error=?,lease_until=NULL WHERE id=? AND lease_token=? AND status='running' AND expires>?",
                       ('failed' if error else 'succeeded', encrypted, b'', error, identifier, token, time.time()))

    def run_once(self, processor=None) -> bool:
        claim = self.claim()
        if not claim:
            return False
        identifier, token, encrypted = claim
        try:
            payload = self._decrypt(encrypted)
            if processor is None:
                from .document_bundle import scan_batch, scan_document
                processor = scan_document if payload['grouped'] else scan_batch
            images = [base64.b64decode(i, validate=True) for i in payload['images']]
            result = processor(images, **payload['options'])
            self.finish(identifier, token, result)
        except InvalidToken:
            with self.connection() as db:
                db.execute("UPDATE jobs SET status='failed',error='JOB_PAYLOAD_DECRYPTION_FAILED',lease_until=NULL WHERE id=? AND lease_token=?", (identifier, token))
        except Exception:
            # Stored errors never include input text, paths, secrets or model output.
            self.finish(identifier, token, error='JOB_PROCESSING_FAILED')
        return True

    def deliver_notification(self, sender=None) -> bool:
        config = webhook_configuration()
        if not config:
            return False
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id,status FROM jobs WHERE notify=1 AND notified=0 AND notification_attempts<6 AND notify_after<=? AND expires>? AND status IN ('succeeded','failed') ORDER BY created LIMIT 1", (now, now)).fetchone()
            if row is None:
                return False
            # Claim notification before network IO. Crash-safe at-least-once;
            # consumers deduplicate the stable id/status event ID.
            db.execute('UPDATE jobs SET notification_attempts=notification_attempts+1,notify_after=? WHERE id=?', (now+300, row['id']))
        url, secret = config
        body = json.dumps({'id': row['id'], 'status': row['status']}, separators=(',', ':')).encode()
        timestamp = str(int(now))
        digest = hmac.new(secret.encode(), timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
        try:
            if sender is None:
                import requests
                sender = requests.post
            response = sender(url, data=body, headers={'Content-Type': 'application/json',
                'X-Document-OCR-Timestamp': timestamp, 'X-Document-OCR-Signature': 'sha256='+digest,
                'X-Document-OCR-Event': row['id']+':'+row['status']}, timeout=10, allow_redirects=False)
            if 200 <= response.status_code < 300:
                with self.connection() as db:
                    db.execute('UPDATE jobs SET notified=1 WHERE id=?', (row['id'],))
        except Exception:
            pass  # Persisted retry schedule above survives process restarts.
        return True


def webhook_configuration():
    from urllib.parse import urlsplit
    url, secret = os.getenv('DOCUMENT_OCR_WEBHOOK_URL'), os.getenv('DOCUMENT_OCR_WEBHOOK_SECRET')
    if not url and not secret:
        return None
    if not url or not secret or len(secret) < 32:
        raise ValueError('INVALID_WEBHOOK_CONFIGURATION')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('INVALID_WEBHOOK_URL')
    return url, secret


def configured_store() -> JobStore | None:
    directory, key = os.getenv('DOCUMENT_OCR_JOBS_DIR'), os.getenv('DOCUMENT_OCR_JOB_KEY')
    if not directory:
        return None
    if not key:
        raise ValueError('MISSING_DOCUMENT_OCR_JOB_KEY')
    return JobStore(directory, key, retention_seconds=int(os.getenv('DOCUMENT_OCR_JOB_RETENTION_SECONDS', '86400')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['worker'])
    parser.parse_args()
    store = configured_store()
    if store is None:
        parser.error('Configure DOCUMENT_OCR_JOBS_DIR and DOCUMENT_OCR_JOB_KEY')
    webhook_configuration()
    from .model_setup import warm_up
    warm_up()
    stopping = False
    def stop(*_args):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        worked = store.run_once()
        store.deliver_notification()
        if not worked:
            time.sleep(1)


if __name__ == '__main__':
    main()
