"""Deployment regressions without credentials, network calls, or live resources."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('render_service', ROOT / 'deploy/cloudrun/render_service.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def test_cloudrun_uses_private_iam_and_secret_references():
    manifest = renderer.service({
        'IMAGE_URI': 'example.test/ocr@sha256:abc',
        'DOCUMENT_OCR_SERVICE_ACCOUNT': 'ocr@example.iam.gserviceaccount.com',
        'DOCUMENT_OCR_KYC_LANGS': 'en,devanagari',
        'GCP_API_TOKEN_SECRET': 'ocr-token',
        'API_TOKEN': 'must-never-be-rendered',
    })
    assert manifest['metadata']['annotations']['run.googleapis.com/invoker-iam-disabled'] == 'false'
    instance = manifest['spec']['template']['spec']
    assert instance['containerConcurrency'] == 1
    container = instance['containers'][0]
    assert container['startupProbe']['httpGet']['path'] == '/ready'
    assert container['livenessProbe']['httpGet']['path'] == '/health'
    assert container['env'][1]['valueFrom']['secretKeyRef']['name'] == 'ocr-token'
    assert 'must-never-be-rendered' not in json.dumps(manifest)


@pytest.mark.parametrize('profile,minimum', [('economy', '0'), ('warm', '1')])
def test_cloudrun_profiles(profile, minimum):
    manifest = renderer.service({'IMAGE_URI': 'image', 'DOCUMENT_OCR_SERVICE_ACCOUNT': 'account', 'DOCUMENT_OCR_PROFILE': profile})
    assert manifest['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/minScale'] == minimum


def test_cloudrun_aborts_when_public_policy_cannot_be_removed(tmp_path):
    executable = tmp_path / 'gcloud'
    log = tmp_path / 'calls.jsonl'
    executable.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['TEST_GCLOUD_CALLS'], 'a') as output:
    output.write(json.dumps(args) + '\\n')
if args[:3] == ['iam', 'service-accounts', 'list']:
    print('document-ocr-ocr-sa@example.iam.gserviceaccount.com')
elif args[:3] == ['run', 'services', 'list']:
    print('document-ocr')
elif args[:3] == ['run', 'services', 'get-iam-policy']:
    print(json.dumps({'bindings': [{'role': 'roles/run.invoker', 'members': ['allUsers']}]}))
elif args[:3] == ['run', 'services', 'set-iam-policy']:
    with open(args[4]) as policy_file:
        policy = json.load(policy_file)
    assert not policy['bindings']
    sys.exit(7)
''')
    executable.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}', TEST_GCLOUD_CALLS=str(log), GCP_PROJECT='example', IMAGE_URI='example.test/ocr:v1')
    for key in ('GCP_API_TOKEN_SECRET', 'GCP_INVOKER_MEMBER', 'DOCUMENT_OCR_SERVICE_ACCOUNT', 'DOCUMENT_OCR_NAME'):
        env.pop(key, None)
    result = subprocess.run(['bash', str(ROOT / 'deploy/cloudrun/deploy.sh')], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 7, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[:3] == ['run', 'services', 'replace'] for call in calls)
    assert not any(call[:2] == ['builds', 'submit'] for call in calls)
