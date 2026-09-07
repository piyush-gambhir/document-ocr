.PHONY: dev test test-py test-ts build benchmark benchmark-kyc docker-build install sync smoke test-ui benchmark-structured

install:
	uv venv --allow-existing
	uv pip install -r requirements.lock
	uv pip install -e '.[dev]' -c requirements.lock
	cd packages/passport-ocr && npm ci

dev:
	PYTHONPATH=$(PWD) uv run --no-sync uvicorn deploy.docker.server:app --host 0.0.0.0 --port 8000 --reload --reload-dir core --reload-dir deploy/docker

test: test-py test-ts test-ui

test-py:
	uv run --no-sync pytest tests/python -v

test-ts:
	cd packages/passport-ocr && npm test

test-ui:
	node --test tests/javascript/review.test.cjs

build:
	cd packages/passport-ocr && npm run build

smoke:
	uv run --no-sync python scripts/ocr_smoke.py

benchmark:
	uv run --no-sync python benchmarks/accuracy.py

benchmark-kyc:
	@test -n "$(KYC_MANIFEST)" || (echo "Set KYC_MANIFEST=/secure/path/manifest.json"; exit 2)
	uv run --no-sync python benchmarks/kyc_accuracy.py --manifest "$(KYC_MANIFEST)" $(if $(KYC_DATASET_ROOT),--dataset-root "$(KYC_DATASET_ROOT)",) $(if $(KYC_REPORT),--output "$(KYC_REPORT)",)

benchmark-structured:
	@test -n "$(STRUCTURED_MANIFEST)" || (echo "Set STRUCTURED_MANIFEST=/secure/path/manifest.json"; exit 2)
	uv run --no-sync python -m benchmarks.structured_accuracy --manifest "$(STRUCTURED_MANIFEST)" $(if $(STRUCTURED_DATASET_ROOT),--dataset-root "$(STRUCTURED_DATASET_ROOT)",) $(if $(STRUCTURED_REPORT),--output "$(STRUCTURED_REPORT)",)

sync:
	cd packages/passport-ocr && bash scripts/sync-python.sh

docker-build:
	docker build -f deploy/docker/Dockerfile -t passport-ocr .

.PHONY: benchmark-public
benchmark-public:
	uv run --no-sync python -m benchmarks.multidoc_accuracy --output "$(or $(OCR_REPORT),benchmark-data/multidoc/report.json)" $(if $(OCR_BASELINE),--baseline "$(OCR_BASELINE)",)
