#!/usr/bin/env bash
# Local deploy. Builds the Docker image and pushes to Docker Hub.
# Run as `bash scripts/deploy.sh [production|development]`.
#
# Reads credentials from .env.deploy.<env> (gitignored).
# See .env.deploy.example for the full list.
#
# Cloud Run / GCP path is stubbed below; uncomment once a GCP project is chosen.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ENV="${1:-production}"
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
echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin

echo "==> Building multi-arch image: ${SHA_TAG}, ${LATEST_TAG}"
docker buildx build \
  --platform "${BUILD_PLATFORMS:-linux/amd64,linux/arm64}" \
  --file "$DOCKERFILE_PATH" \
  --tag "$SHA_TAG" \
  --tag "$LATEST_TAG" \
  --push \
  .

echo "==> Pushed:"
echo "    $SHA_TAG"
echo "    $LATEST_TAG"

# --------------------------------------------------------------------------
# Cloud Run path — uncomment once GCP_PROJECT is chosen and gcloud is set up.
#
# : "${GCP_PROJECT:?set GCP_PROJECT in ${DEPLOY_ENV_FILE}}"
# : "${GCP_REGION:?set GCP_REGION in ${DEPLOY_ENV_FILE}}"
# : "${GCP_CONFIG:?set GCP_CONFIG in ${DEPLOY_ENV_FILE}}"
#
# gcloud config configurations activate "$GCP_CONFIG"
# gcloud run deploy "document-ocr-${ENV}" \
#   --image "$SHA_TAG" \
#   --region "$GCP_REGION" \
#   --project "$GCP_PROJECT" \
#   --platform managed \
#   --allow-unauthenticated
# --------------------------------------------------------------------------
