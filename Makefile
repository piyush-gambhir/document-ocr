.PHONY: dev test test-py test-ts build benchmark docker-build install

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

docker-build:
	docker build -f deploy/docker/Dockerfile -t passport-ocr .
