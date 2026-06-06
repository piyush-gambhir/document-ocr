"""Fast guards for the labelled KYC dataset + accuracy-scoring logic.

Does NOT run OCR (the real end-to-end run is `make benchmark-documents`). This
keeps the unit suite fast while protecting the manifest structure and the
field-matching logic the benchmark depends on.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import synth_common as sc  # noqa: E402


def _load_benchmark_module():
    path = REPO_ROOT / "benchmarks" / "document_accuracy.py"
    spec = importlib.util.spec_from_file_location("document_accuracy_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench():
    return _load_benchmark_module()


class TestManifestIntegrity:
    def test_dataset_has_labelled_images(self):
        items = sc.load_all_manifests()
        assert len(items) >= 8, "expected several labelled specimens"

    def test_every_image_exists_and_is_well_formed(self, bench):
        items = sc.load_all_manifests()
        for item in items:
            assert item.document_type in bench._BLOCK_KEY, item.document_type
            assert (REPO_ROOT / item.file).exists(), f"missing image {item.file}"
            assert item.fields, f"no ground-truth fields for {item.file}"

    def test_all_document_types_covered(self):
        types = {i.document_type for i in sc.load_all_manifests()}
        assert {"pan", "aadhaar", "driving_licence", "voter_id"} <= types


class TestFieldMatch:
    def test_exact_and_case_insensitive(self, bench):
        assert bench._field_match("name", "ROHIT SHARMA", "ROHIT SHARMA")
        assert bench._field_match("name", "Rohit Sharma", "ROHIT  SHARMA")

    def test_mismatch(self, bench):
        assert not bench._field_match("panNumber", "ABCPE1234F", "ABCPE9999F")

    def test_none_actual_is_miss(self, bench):
        assert not bench._field_match("name", "ANYTHING", None)

    def test_boolean_fields(self, bench):
        assert bench._field_match("checksumValid", True, True)
        assert not bench._field_match("checksumValid", True, False)

    def test_address_fuzzy_allows_reflow(self, bench):
        gt = "S/O Mohan Lal, 24 Gandhi Road, Jaipur, Rajasthan - 302015"
        ocr = "S/O Mohan Lal 24 Gandhi Road, Jaipur, Rajasthan, PIN: 302015"
        assert bench._field_match("address", gt, ocr)

    def test_address_fuzzy_rejects_unrelated(self, bench):
        assert not bench._field_match("address", "24 Gandhi Road, Jaipur", "99 Marine Drive, Mumbai")


class TestDegradations:
    def test_all_degradations_run(self):
        from PIL import Image

        img = Image.new("RGB", (400, 300), "white")
        for name in sc.DEGRADATIONS:
            out = sc.degrade(img, name)
            assert out.size[0] > 0 and out.size[1] > 0
        assert isinstance(sc.to_png_bytes(img), bytes)
