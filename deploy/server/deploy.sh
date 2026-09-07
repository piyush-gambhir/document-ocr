#!/usr/bin/env bash
# Run on the target server (or use Docker's existing remote context).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"
source deploy/common.sh
hosting_defaults
require_command docker
: "${DOMAIN:?Set DOMAIN to a DNS name pointing to this server}"
: "${API_TOKEN:?Set API_TOKEN}"
COMPOSE=(docker compose -p "$DOCUMENT_OCR_NAME" -f deploy/server/compose.yaml)
if [[ "${DOCUMENT_OCR_JOBS_ENABLED:-false}" == true ]]; then
  : "${DOCUMENT_OCR_JOB_KEY:?Set DOCUMENT_OCR_JOB_KEY for encrypted persistent jobs}"
  COMPOSE+=(-f deploy/server/compose.jobs.yaml --profile jobs)
fi
"${COMPOSE[@]}" config --quiet
if [[ -n "${IMAGE_URI:-}" ]]; then
  "${COMPOSE[@]}" pull ocr
  "${COMPOSE[@]}" up --detach --wait --no-build
else
  "${COMPOSE[@]}" up --detach --wait --build
fi
printf 'Document OCR is available at https://%s (Bearer authentication required).\n' "$DOMAIN"
