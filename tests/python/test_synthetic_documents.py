import pytest

from benchmarks.multidoc_accuracy import expected
from benchmarks.public_data import fetch_bytes, inspect_samples
from benchmarks.synthetic_documents import PROFILES, definition, generate
from core.document_registry import DOCUMENT_PROFILES


def test_generated_images_cover_every_registered_profile_with_traceable_truth(tmp_path):
    root = tmp_path / 'images'
    manifest = generate(root, tmp_path / 'manifest.json')
    assert set(PROFILES) == set(DOCUMENT_PROFILES)
    assert len(manifest['cases']) == 105
    assert inspect_samples(manifest, root)['integrity'] == 'passed'
    for kind in PROFILES:
        cases = [c for c in manifest['cases'] if c['profile'] == kind]
        assert len(cases) == 6
        assert len({c['group'] for c in cases}) == 2
        assert {c['capture'] for c in cases} == {'clean', 'jpeg', 'tilted'}
        fields, _ = expected(cases[0], root)
        assert fields == definition(kind, 0)['fields']
    assert len([c for c in manifest['cases'] if c['profile'] == 'negative_control']) == 15
    # Reproduction is byte-identical on the pinned renderer, independent of OCR.
    assert generate(root, tmp_path / 'second.json') == manifest
    assert sum(f['bytes'] for f in manifest['files']) < 15 * 1024**2
    image = root / manifest['cases'][0]['image']
    image.write_bytes(image.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='checksum'):
        inspect_samples(manifest, root)


def test_local_generated_assets_are_never_downloaded():
    with pytest.raises(ValueError, match='generator'):
        fetch_bytes({'kind': 'generated'}, {})


def test_truth_contains_ssn_ein_masked_identity_and_both_visa_widths():
    assert {definition('us_w9', i)['fields']['taxpayerIdType'] for i in range(2)} == {'ssn', 'ein'}
    assert definition('aadhaar', 1)['fields']['aadhaarNumber'] is None
    assert definition('aadhaar', 1)['fields']['aadhaarMasked'] is True
    assert [len(definition('visa', i)['mrzRaw'][0]) for i in range(2)] == [44, 36]
    assert {definition('us_i94', i)['fields']['admitUntil'] for i in range(2)} == {'D/S', '2030-06-01'}
