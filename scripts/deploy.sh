#!/usr/bin/env bash
# Local deploy. Builds the Docker image and pushes to Docker Hub.
# Run as `bash scripts/deploy.sh [production|development]`.
#
# Reads credentials from .env.deploy.<env> (gitignored).
# See .env.deploy.example for the full list.
#
# For Cloud Run, Lambda, Cloudflare or a server, use the kits in HOSTING.md.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ENV="${1:-production}"
case "$ENV" in production|development) ;; *) printf 'Expected production or development\n' >&2; exit 1;; esac
DEPLOY_ENV_FILE=".env.deploy.${ENV}"

if [[ ! -f "$DEPLOY_ENV_FILE" ]]; then
  echo "error: ${DEPLOY_ENV_FILE} not found in $(pwd)" >&2
  echo "       copy .env.deploy.example to ${DEPLOY_ENV_FILE} and fill in your values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$DEPLOY_ENV_FILE"
set +a
source "$ROOT_DIR/deploy/common.sh"
hosting_defaults
require_command docker
docker buildx version >/dev/null

: "${DOCKERHUB_USERNAME:?set DOCKERHUB_USERNAME in ${DEPLOY_ENV_FILE}}"
: "${DOCKERHUB_TOKEN:?set DOCKERHUB_TOKEN in ${DEPLOY_ENV_FILE}}"

IMAGE_NAME="${IMAGE_NAME:-${DOCKERHUB_USERNAME}/document-ocr}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-deploy/docker/Dockerfile}"

# Tag derivation: env-suffix + git short sha + UTC date
GIT_SHA="$(git rev-parse --short HEAD)"
UTC_DATE="$(date -u +%Y%m%d)"
SHA_TAG="${IMAGE_NAME}:${ENV}-${UTC_DATE}-${GIT_SHA}"
LATEST_TAG="${IMAGE_NAME}:${ENV}"
if [[ "$ENV" == "production" ]]; then
  LATEST_TAG="${IMAGE_NAME}:latest"
fi

echo "==> Logging into Docker Hub as ${DOCKERHUB_USERNAME}"
printf '%s' "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin

echo "==> Building multi-arch image: ${SHA_TAG}, ${LATEST_TAG}"
docker buildx build \
  --platform "${BUILD_PLATFORMS:-linux/amd64,linux/arm64}" \
  --file "$DOCKERFILE_PATH" \
  --build-arg "DOCUMENT_OCR_KYC_LANGS=$DOCUMENT_OCR_KYC_LANGS" \
  --tag "$SHA_TAG" \
  --tag "$LATEST_TAG" \
  --push \
  .

echo "==> Pushed:"
echo "    $SHA_TAG"
echo "    $LATEST_TAG"
