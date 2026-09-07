"""Prepare a tiny set of reviewed official specimens, preserving source bytes.

These agent-transcribed labels are contract coverage, not an independently
annotated population benchmark. Images stay outside Git; reviewed labels are
checked in and checksum-pinned by the manifest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.public_data import (
    SAMPLE_ROOT, check_bytes, fetch_bytes, inspect_samples, sample_path,
    validate_manifest,
)

MANIFEST = Path(__file__).with_name('additional_profile_samples.json')
TRUTH = Path(__file__).with_name('specimen_truth')


def prepare(root: Path = SAMPLE_ROOT, *, fetch: bool = False) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    validate_manifest(manifest, root)
    for record in manifest['files']:
        destination = sample_path(root, record['path'])
        if record['kind'] == 'generated':
            raw = sample_path(TRUTH, record['sourceFile']).read_bytes()
        elif destination.exists():
            raw = destination.read_bytes()
        elif fetch:
            raw = fetch_bytes(record, {})
        else:
            raise FileNotFoundError(f"Missing {record['path']}; rerun with --fetch")
        check_bytes(raw, record)
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + '.part')
            partial.write_bytes(raw)
            partial.replace(destination)
        else:
            check_bytes(destination.read_bytes(), record)
    return inspect_samples(manifest, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SAMPLE_ROOT)
    parser.add_argument('--fetch', action='store_true', help='Fetch only missing pinned specimen images')
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.root, fetch=args.fetch), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
