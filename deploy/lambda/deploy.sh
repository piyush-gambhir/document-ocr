#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"
source deploy/common.sh
hosting_defaults
require_command sam
require_command aws
export AWS_REGION="${AWS_REGION:-ap-south-1}"
STACK="${AWS_STACK_NAME:-$DOCUMENT_OCR_NAME}"
PARAMETERS=("KycLanguages=$DOCUMENT_OCR_KYC_LANGS" "InputBucket=${DOCUMENT_OCR_S3_BUCKET:-}" "InputPrefix=${DOCUMENT_OCR_S3_PREFIX:-uploads/}")
TEMPLATE=deploy/lambda/template.yaml
if [[ -z "${IMAGE_URI:-}" ]]; then
  require_command docker
  export DOCKER_DEFAULT_PLATFORM=linux/amd64
  sam build --template-file "$TEMPLATE" --parameter-overrides "${PARAMETERS[@]}"
  TEMPLATE=.aws-sam/build/template.yaml
else
  PARAMETERS+=("ImageUri=$IMAGE_URI")
fi
sam deploy --template-file "$TEMPLATE" --stack-name "$STACK" --region "$AWS_REGION" --resolve-image-repos --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides "${PARAMETERS[@]}" --no-fail-on-empty-changeset
aws cloudformation describe-stacks --stack-name "$STACK" --region "$AWS_REGION" --query 'Stacks[0].Outputs' --output json
