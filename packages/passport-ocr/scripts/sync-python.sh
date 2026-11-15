#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PACKAGE_DIR/../.." && pwd)"


rm -rf "$PACKAGE_DIR/python/core"
cp -r "$REPO_ROOT/core" "$PACKAGE_DIR/python/core"
find "$PACKAGE_DIR/python" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true


cp "$REPO_ROOT/requirements.lock" "$PACKAGE_DIR/python/requirements.lock"


cp "$REPO_ROOT/deploy/docker/server.py" "$PACKAGE_DIR/python/server.py"

echo "[sync-python] Synced core/ and server.py into packages/passport-ocr/python/"
