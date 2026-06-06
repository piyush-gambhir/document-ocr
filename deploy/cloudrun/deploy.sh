#!/usr/bin/env bash
# Deploy document-ocr to Google Cloud Run.
#
# Run as `bash deploy/cloudrun/deploy.sh [production|development]`.
#
# Builds the container from deploy/docker/Dockerfile, pushes it to Google
# Artifact Registry, then deploys it to Cloud Run via the service.yaml manifest.
#
# Reads credentials from .env.deploy.<env> (gitignored). See .env.deploy.example
# for the required GCP_* values.
#
# Prerequisites: gcloud CLI authenticated (`gcloud auth login`), Docker, and an
# Artifact Registry repo named `document-ocr` in the target region.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

ENV="${1:-production}"
DEPLOY_ENV_FILE=".env.deploy.${ENV}"

if [[ ! -f "$DEPLOY_ENV_FILE" ]]; then
  echo "error: ${DEPLOY_ENV_FILE} not found in $(pwd)" >&2
  echo "       copy .env.deploy.example to ${DEPLOY_ENV_FILE} and fill in the GCP_* values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$DEPLOY_ENV_FILE"
set +a

: "${GCP_PROJECT:?set GCP_PROJECT in ${DEPLOY_ENV_FILE}}"
: "${GCP_REGION:?set GCP_REGION in ${DEPLOY_ENV_FILE}}"

SERVICE_NAME="${CLOUD_RUN_SERVICE:-document-ocr}"
AR_REPO="${GCP_AR_REPO:-document-ocr}"
IMAGE_BASE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}/document-ocr"

GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"
UTC_DATE="$(date -u +%Y%m%d)"
IMAGE_TAG="${IMAGE_BASE}:${ENV}-${UTC_DATE}-${GIT_SHA}"

if [[ -n "${GCP_CONFIG:-}" ]]; then
  gcloud config configurations activate "$GCP_CONFIG"
fi

echo "==> Configuring docker auth for Artifact Registry"
gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev" --quiet

echo "==> Building and pushing ${IMAGE_TAG}"
docker build --file deploy/docker/Dockerfile --tag "$IMAGE_TAG" .
docker push "$IMAGE_TAG"

echo "==> Deploying to Cloud Run service '${SERVICE_NAME}'"
# Render the service manifest with the freshly-pushed image, then apply it.
RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT
sed -e "s|IMAGE_PLACEHOLDER|${IMAGE_TAG}|" \
    -e "s|name: document-ocr|name: ${SERVICE_NAME}|" \
    deploy/cloudrun/service.yaml > "$RENDERED"

gcloud run services replace "$RENDERED" \
  --region "$GCP_REGION" \
  --project "$GCP_PROJECT"

# Public, unauthenticated access. Remove this block for an internal service.
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region "$GCP_REGION" \
  --project "$GCP_PROJECT" \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --quiet

URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region "$GCP_REGION" --project "$GCP_PROJECT" \
  --format='value(status.url)')"

echo "==> Deployed: ${URL}"
echo "    Health:  ${URL}/health"
echo "    Scan:    curl -F image=@passport.jpg ${URL}/scan"
