.PHONY: dev test test-py test-ts build benchmark benchmark-documents gen-documents docker-build install sync

install:
	uv sync
	cd packages/passport-ocr && npm install

dev:
	PYTHONPATH=$(PWD) uv run uvicorn deploy.docker.server:app --host 0.0.0.0 --port 8000 --reload --reload-dir core --reload-dir deploy/docker

test: test-py test-ts

test-py:
	uv run pytest tests/python -v

test-ts:
	cd packages/passport-ocr && npx vitest run ../../tests/typescript

build:
	cd packages/passport-ocr && npm run build

benchmark:
	uv run python benchmarks/accuracy.py

# End-to-end KYC accuracy on the labelled synthetic dataset (clean + degraded).
benchmark-documents:
	uv run python benchmarks/document_accuracy.py

# Regenerate the labelled synthetic KYC images from their generators.
gen-documents:
	uv run python scripts/generate_synthetic_pan.py
	uv run python scripts/generate_synthetic_aadhaar.py
	uv run python scripts/generate_synthetic_driving_licence.py
	uv run python scripts/generate_synthetic_voter_id.py

sync:
	cd packages/passport-ocr && bash scripts/sync-python.sh

docker-build:
	docker build -f deploy/docker/Dockerfile -t passport-ocr .
