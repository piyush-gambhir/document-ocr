"""Every supported profile must retain an honest dataset/coverage entry."""
import json
from pathlib import Path

from core.document_registry import DOCUMENT_PROFILES


def test_dataset_coverage_tracks_registry_and_resolves_all_sources():
    catalog = json.loads(Path('benchmarks/document_dataset_coverage.json').read_text())
    assert set(catalog['profiles']) == set(DOCUMENT_PROFILES)
    for profile in catalog['profiles'].values():
        assert profile['status'] and profile['gaps'] and profile['smallSamplePlan']
        assert set(profile['sourceIds']) <= set(catalog['sources'])
    for source in catalog['sources'].values():
        assert source['url'].startswith('https://')
        assert source['kind'] and source['terms'] and source['labels'] and source['verified']
