#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

echo "Starting passport-ocr dev server on http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo ""

PYTHONPATH="$ROOT_DIR" uv run uvicorn deploy.docker.server:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --reload-dir core \
  --reload-dir deploy/docker
