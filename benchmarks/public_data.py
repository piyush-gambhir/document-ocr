"""Linked dataset catalog and bounded, checksum-pinned evaluation samples.

Never downloads full archives. Sample ranges are indexed from verified releases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
import zlib

CATALOG = Path(__file__).with_name('public_datasets.json')
SAMPLES = Path(__file__).with_name('public_samples.json')
SAMPLE_ROOT = Path('benchmark-data/samples')
MAX_BYTES = 100 * 1024**2


def sample_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not name or Path(name).is_absolute() or '..' in Path(name).parts or not path.is_relative_to(root.resolve()):
        raise ValueError('sample path must stay inside its root')
    return path


def check_bytes(raw: bytes, record: dict) -> None:
    if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError(f"sample checksum/size mismatch: {record['path']}")


def read_url(url: str, limit: int, *, offset: int | None = None, total: int | None = None) -> bytes:
    if urllib.parse.urlsplit(url).scheme != 'https' or not 0 < limit <= MAX_BYTES:
        raise ValueError('HTTPS and a bounded response size are required')
    headers = {'Accept-Encoding': 'identity', 'User-Agent': 'document-ocr-samples/1'}
    if offset is not None:
        headers['Range'] = f'bytes={offset}-{offset + limit - 1}'
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        if offset is not None:
            expected = f'bytes {offset}-{offset + limit - 1}/{total}'
            if response.status != 206 or response.headers.get('Content-Range') != expected:
                raise ValueError('server did not honor the exact sample range; full downloads are refused')
        elif response.status != 200:
            raise ValueError('unexpected sample response status')
        raw = response.read(limit + 1)
    if len(raw) > limit or (offset is not None and len(raw) != limit):
        raise ValueError('sample response size mismatch')
    return raw


def fetch_bytes(record: dict, rows: dict) -> bytes:
    if record.get('kind') == 'direct':
        return read_url(record['url'], record['bytes'])
    if record.get('kind') in {'cord-row', 'symage-row'}:
        url = record['url']
        if url not in rows:
            result = json.loads(read_url(url, 1024**2))
            if len(result['rows']) != 1 or result['rows'][0].get('truncated_cells'):
                raise ValueError('dataset row missing or truncated')
            rows[url] = result['rows'][0]['row']
        row = rows[url]
        if record['column'] == 'truth':
            if record['kind'] == 'symage-row':
                return json.dumps({key: row[key] for key in
                                   ('id', 'identity_id', 'form_id', 'page', 'funsd_json')},
                                  sort_keys=True, separators=(',', ':')).encode()
            return json.dumps(json.loads(row['ground_truth']), sort_keys=True, separators=(',', ':')).encode()
        src = row['image']['src']
        parsed = urllib.parse.urlsplit(src)
        if parsed.hostname != 'datasets-server.huggingface.co' or f"/--/{record['revision']}/--/" not in parsed.path:
                raise ValueError('dataset viewer revision/host changed; explicitly review sample updates')
        return read_url(src, record['bytes'])
    raw = read_url(record['url'], record['length'], offset=record['offset'], total=record['archiveBytes'])
    if record['compression'] == 'stored':
        return raw
    if record['compression'] != 'deflate':
        raise ValueError('unsupported sample compression')
    decoder = zlib.decompressobj(-15)
    raw = decoder.decompress(raw, record['bytes'] + 1)
    if len(raw) > record['bytes'] or not decoder.eof or decoder.unused_data:
        raise ValueError('invalid or oversized compressed sample')
    return raw


def validate_manifest(manifest: dict, root: Path) -> None:
    if manifest['schemaVersion'] != 1 or not manifest['cases']:
        raise ValueError('unsupported or empty sample manifest')
    files = manifest['files']
    paths = [f['path'] for f in files]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate sample paths')
    if any(not isinstance(f['bytes'], int) or not 0 < f['bytes'] <= MAX_BYTES for f in files):
        raise ValueError('invalid sample size')
    if sum(f['bytes'] for f in files) > MAX_BYTES:
        raise ValueError('sample exceeds the fixed 100 MiB limit')
    for f in files:
        sample_path(root, f['path'])
        if f.get('kind') not in {'cord-row', 'symage-row', 'direct'}:
            if not (0 < f['length'] <= MAX_BYTES and 0 <= f['offset'] < f['archiveBytes']
                    and f['offset'] + f['length'] <= f['archiveBytes']):
                raise ValueError('invalid archive range')
    # Include a bounded metadata allowance for each unique dataset row request.
    transfer = sum(f.get('length', f['bytes']) for f in files)
    transfer += len({f['url'] for f in files if f.get('kind') in {'cord-row', 'symage-row'}}) * 1024**2
    if transfer > MAX_BYTES:
        raise ValueError('sample transfers exceed the fixed 100 MiB limit')
    ids = set()
    for case in manifest['cases']:
        if case['id'] in ids or not case['group']:
            raise ValueError('duplicate case ID or missing identity group')
        ids.add(case['id'])
        for key in ('image', 'truth', 'geometry'):
            if key in case and case[key] not in paths:
                raise ValueError('case references an unpinned file')


def inspect_samples(manifest: dict, root: Path) -> dict:
    from PIL import Image

    validate_manifest(manifest, root)
    for record in manifest['files']:
        check_bytes(sample_path(root, record['path']).read_bytes(), record)
    counts = {}
    for case in manifest['cases']:
        with Image.open(sample_path(root, case['image'])) as image:
            image.load()
            size = {'width': image.width, 'height': image.height}
        truth = json.loads(sample_path(root, case['truth']).read_text())
        if 'truthSelector' in case:
            name = case['truthSelector']['viaFilename']
            matches = [v for v in truth['_via_img_metadata'].values() if v['filename'] == name]
            if len(matches) != 1 or not any(r['region_attributes'].get('value') for r in matches[0]['regions']):
                raise ValueError('missing or ambiguous MIDV text truth')
        elif case['dataset'] == 'cord-v2':
            if truth['meta']['image_size'] != size or not truth['valid_line']:
                raise ValueError('CORD image/annotation mismatch')
        elif case['dataset'] == 'midv-lait':
            if not truth['fields']:
                raise ValueError('missing LAIT fields')
        elif case['dataset'] == 'idnet-part3':
            if not truth.get('license_number'):
                raise ValueError('missing IDNet licence truth')
        elif case['dataset'] == 'symage-us-forms':
            if truth['form_id'] != case['formId'] or not json.loads(truth['funsd_json']):
                raise ValueError('missing or mismatched form annotations')
        if 'geometry' in case:
            json.loads(sample_path(root, case['geometry']).read_text())
        counts[case['dataset']] = counts.get(case['dataset'], 0) + 1
    return {'schemaVersion': 1, 'manifestSha256': hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            'cases': len(manifest['cases']), 'identityGroups': len({c['group'] for c in manifest['cases']}),
            'files': len(manifest['files']), 'bytes': sum(f['bytes'] for f in manifest['files']),
            'datasets': counts, 'integrity': 'passed', 'ocrMeasured': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'fetch-samples', 'verify-samples'])
    parser.add_argument('--root', type=Path, default=SAMPLE_ROOT)
    parser.add_argument('--manifest', type=Path, default=SAMPLES)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'list':
        for entry in json.loads(CATALOG.read_text())['datasets']:
            print(f"{entry['id']} | {entry['access']} | {entry['license']} | {entry['source']}")
        return 0
    try:
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest, args.root)
        if args.command == 'fetch-samples':
            rows = {}
            for record in manifest['files']:
                path = sample_path(args.root, record['path'])
                if path.exists():
                    check_bytes(path.read_bytes(), record)
                    continue
                raw = fetch_bytes(record, rows)
                check_bytes(raw, record)
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_name(path.name + '.part')
                partial.write_bytes(raw)
                partial.replace(path)
        report = inspect_samples(manifest, args.root)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zlib.error) as error:
        print(f'FAILED: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
