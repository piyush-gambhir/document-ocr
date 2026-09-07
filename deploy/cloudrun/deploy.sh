#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"
source deploy/common.sh
if [[ $# -gt 0 ]]; then
  [[ "$1" == production || "$1" == development ]] || { printf 'Optional argument must be production or development\n' >&2; exit 1; }
  set -a
  source ".env.deploy.$1"
  set +a
fi
hosting_defaults
require_command gcloud
require_command python3
: "${GCP_PROJECT:?Set GCP_PROJECT}"
export GCP_REGION="${GCP_REGION:-asia-south1}"
AR_REPO="${GCP_AR_REPO:-document-ocr}"
export DOCUMENT_OCR_SERVICE_ACCOUNT="${DOCUMENT_OCR_SERVICE_ACCOUNT:-${DOCUMENT_OCR_NAME:0:23}-ocr-sa@${GCP_PROJECT}.iam.gserviceaccount.com}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com iam.googleapis.com secretmanager.googleapis.com --project "$GCP_PROJECT" --quiet
# List succeeds or the script fails; permission failures never mean "not found".
ACCOUNTS="$(gcloud iam service-accounts list --project "$GCP_PROJECT" --filter="email=${DOCUMENT_OCR_SERVICE_ACCOUNT}" --format='value(email)')"
if [[ -z "$ACCOUNTS" ]]; then
  gcloud iam service-accounts create "${DOCUMENT_OCR_SERVICE_ACCOUNT%%@*}" --project "$GCP_PROJECT" --display-name 'Document OCR runtime' --quiet
fi
if [[ -n "${GCP_API_TOKEN_SECRET:-}" ]]; then
  gcloud secrets add-iam-policy-binding "$GCP_API_TOKEN_SECRET" --project "$GCP_PROJECT" --member="serviceAccount:${DOCUMENT_OCR_SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
fi

make_private() {
  gcloud run services get-iam-policy "$DOCUMENT_OCR_NAME" --region "$GCP_REGION" --project "$GCP_PROJECT" --format=json > "$TMP_DIR/policy.json"
  python3 - "$TMP_DIR/policy.json" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as source:
    policy = json.load(source)
for binding in policy.get('bindings', []):
    if binding.get('role') == 'roles/run.invoker':
        binding['members'] = [member for member in binding.get('members', []) if member not in {'allUsers', 'allAuthenticatedUsers'}]
policy['bindings'] = [binding for binding in policy.get('bindings', []) if binding.get('members')]
with open(path, 'w') as target:
    json.dump(policy, target)
PY
  gcloud run services set-iam-policy "$DOCUMENT_OCR_NAME" "$TMP_DIR/policy.json" --region "$GCP_REGION" --project "$GCP_PROJECT" --quiet >/dev/null
}
EXISTING="$(gcloud run services list --region "$GCP_REGION" --project "$GCP_PROJECT" --filter="metadata.name=${DOCUMENT_OCR_NAME}" --format='value(metadata.name)')"
if [[ -n "$EXISTING" ]]; then
  make_private
  gcloud run services update "$DOCUMENT_OCR_NAME" --invoker-iam-check --region "$GCP_REGION" --project "$GCP_PROJECT" --quiet
fi

if [[ -z "${IMAGE_URI:-}" ]]; then
  REPOSITORIES="$(gcloud artifacts repositories list --project "$GCP_PROJECT" --location "$GCP_REGION" --filter="name:${AR_REPO}" --format='value(name)')"
  if [[ "$REPOSITORIES" != *"/repositories/${AR_REPO}"* ]]; then
    gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location "$GCP_REGION" --project "$GCP_PROJECT" --quiet
  fi
  export IMAGE_URI="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}/${DOCUMENT_OCR_NAME}:$(date -u +%Y%m%d%H%M%S)"
  gcloud builds submit . --project "$GCP_PROJECT" --region "$GCP_REGION" --config deploy/cloudrun/cloudbuild.yaml --substitutions="^|^_IMAGE_URI=${IMAGE_URI}|_KYC_LANGS=${DOCUMENT_OCR_KYC_LANGS}" --quiet
fi
export IMAGE_URI
python3 deploy/cloudrun/render_service.py > "$TMP_DIR/service.json"
gcloud run services replace "$TMP_DIR/service.json" --region "$GCP_REGION" --project "$GCP_PROJECT" --quiet
make_private
if [[ -n "${GCP_INVOKER_MEMBER:-}" ]]; then
  [[ "$GCP_INVOKER_MEMBER" != allUsers && "$GCP_INVOKER_MEMBER" != allAuthenticatedUsers ]] || { printf 'A named IAM invoker is required\n' >&2; exit 1; }
  gcloud run services add-iam-policy-binding "$DOCUMENT_OCR_NAME" --member "$GCP_INVOKER_MEMBER" --role roles/run.invoker --region "$GCP_REGION" --project "$GCP_PROJECT" --quiet >/dev/null
fi
URL="$(gcloud run services describe "$DOCUMENT_OCR_NAME" --region "$GCP_REGION" --project "$GCP_PROJECT" --format='value(status.url)')"
printf 'Deployed private Cloud Run service: %s\nUse an audience-matched Google ID token; see HOSTING.md.\n' "$URL"
