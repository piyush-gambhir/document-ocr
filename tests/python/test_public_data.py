"""Sample downloads must remain bounded, immutable, and independent of OCR."""
import hashlib
import io
import json
import zlib
from unittest.mock import patch

import pytest

from benchmarks import public_data as data


def record(raw=b'sample'):
    return {'path': 'example/image.png', 'url': 'https://example.org/source.zip',
            'offset': 40, 'length': len(raw), 'archiveBytes': 100,
            'compression': 'stored', 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


class Response(io.BytesIO):
    def __init__(self, raw, status=206, content_range='bytes 40-45/100'):
        super().__init__(raw)
        self.status = status
        self.headers = {'Content-Range': content_range}


def test_range_request_and_exact_payload():
    with patch.object(data.urllib.request, 'urlopen', return_value=Response(b'sample')) as request:
        assert data.fetch_bytes(record(), {}) == b'sample'
    assert request.call_args.args[0].get_header('Range') == 'bytes=40-45'


@pytest.mark.parametrize('status,header,raw', [
    (200, 'bytes 40-45/100', b'sample'),
    (206, 'bytes 0-5/100', b'sample'),
    (206, 'bytes 40-45/101', b'sample'),
    (206, 'bytes 40-45/100', b'short'),
    (206, 'bytes 40-45/100', b'toolong'),
])
def test_full_download_wrong_range_and_short_response_refused(status, header, raw):
    with patch.object(data.urllib.request, 'urlopen', return_value=Response(raw, status, header)):
        with pytest.raises(ValueError):
            data.fetch_bytes(record(), {})


def test_deflate_member_and_decompression_limit():
    compressor = zlib.compressobj(wbits=-15)
    compressed = compressor.compress(b'sample') + compressor.flush()
    r = {**record(), 'compression': 'deflate', 'length': len(compressed)}
    with patch.object(data, 'read_url', return_value=compressed):
        assert data.fetch_bytes(r, {}) == b'sample'
        with pytest.raises(ValueError):
            data.fetch_bytes({**r, 'bytes': 3}, {})
        with pytest.raises(ValueError):
            data.fetch_bytes({**r, 'compression': 'unknown'}, {})


def test_checksum_rejects_same_size_corruption():
    with pytest.raises(ValueError, match='checksum'):
        data.check_bytes(b'Sample', record())


@pytest.mark.parametrize('path', ['../escape', '/tmp/escape', 'a/../../escape'])
def test_paths_cannot_escape_root(tmp_path, path):
    with pytest.raises(ValueError):
        data.sample_path(tmp_path, path)


def test_symlink_cannot_escape_root(tmp_path):
    (tmp_path / 'escape').symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        data.sample_path(tmp_path, 'escape/image.png')


def test_catalog_and_sample_contract(tmp_path):
    catalog = json.loads(data.CATALOG.read_text())
    manifest = json.loads(data.SAMPLES.read_text())
    data.validate_manifest(manifest, tmp_path)
    entries = {d['id']: d for d in catalog['datasets']}
    assets = {a['url']: a for d in entries.values() for a in d.get('assets', [])}
    for f in manifest['files']:
        if f.get('kind') != 'cord-row':
            assert f['archiveChecksum'] == assets[f['url']]['checksum']
            assert f['archiveBytes'] == assets[f['url']]['bytes']
    assert len(manifest['cases']) == 40
    assert {c['dataset'] for c in manifest['cases']} <= entries.keys()
    assert len({c['group'] for c in manifest['cases']}) == 18


def test_manifest_budget_and_missing_truth(tmp_path):
    manifest = {'schemaVersion': 1, 'files': [record()],
                'cases': [{'id': 'a', 'group': 'a', 'image': 'example/image.png', 'truth': 'missing'}]}
    with pytest.raises(ValueError, match='unpinned'):
        data.validate_manifest(manifest, tmp_path)
    manifest['files'][0]['bytes'] = data.MAX_BYTES + 1
    with pytest.raises(ValueError, match='size'):
        data.validate_manifest(manifest, tmp_path)


def test_cord_revision_and_truncation_fail_closed():
    r = {**record(), 'kind': 'cord-row', 'column': 'image', 'revision': 'pinned'}
    wrong = {'rows': [{'row': {'image': {'src': 'https://datasets-server.huggingface.co/--/changed/--/image.jpg'}}, 'truncated_cells': []}]}
    with patch.object(data, 'read_url', return_value=json.dumps(wrong).encode()):
        with pytest.raises(ValueError, match='revision'):
            data.fetch_bytes(r, {})
    wrong['rows'][0]['truncated_cells'] = ['ground_truth']
    with patch.object(data, 'read_url', return_value=json.dumps(wrong).encode()):
        with pytest.raises(ValueError, match='truncated'):
            data.fetch_bytes(r, {})


def test_cached_corrupt_sample_is_not_silently_replaced(tmp_path):
    manifest = {'schemaVersion': 1, 'files': [record()], 'cases': [
        {'id': 'a', 'group': 'a', 'image': 'example/image.png', 'truth': 'example/image.png'}]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    cached = tmp_path / 'example/image.png'
    cached.parent.mkdir()
    cached.write_bytes(b'Sample')
    with patch.object(data, 'fetch_bytes') as fetch:
        assert data.main(['fetch-samples', '--root', str(tmp_path), '--manifest', str(path)]) == 1
        fetch.assert_not_called()


def test_expansion_manifest_is_bounded_and_has_no_original_identity_overlap(tmp_path):
    from benchmarks.multidoc_accuracy import EXPANSION
    original = json.loads(data.SAMPLES.read_text())
    expansion = json.loads(EXPANSION.read_text())
    data.validate_manifest(expansion, tmp_path)
    assert len(expansion['cases']) == 22
    assert not {c['group'] for c in original['cases']} & {c['group'] for c in expansion['cases']}
    assert sum(f['bytes'] for f in expansion['files']) < data.MAX_BYTES


def test_symage_row_truth_and_revision_are_pinned_without_shard_download():
    row = {'id': 'opaque', 'identity_id': 1, 'form_id': 'w9', 'page': 0,
           'funsd_json': '[]', 'image': {'src': 'https://datasets-server.huggingface.co/--/rev/--/image.jpg'}}
    source = {'rows': [{'row': row, 'truncated_cells': []}]}
    rec = {**record(), 'kind': 'symage-row', 'column': 'truth', 'revision': 'rev'}
    with patch.object(data, 'read_url', return_value=json.dumps(source).encode()) as read:
        truth = json.loads(data.fetch_bytes(rec, {}))
        assert truth['funsd_json'] == '[]'
        assert 'image' not in truth
        read.assert_called_once()
