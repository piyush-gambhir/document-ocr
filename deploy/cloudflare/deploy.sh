#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source ../common.sh
hosting_defaults
require_command node
require_command npm
if [[ ! -x node_modules/.bin/wrangler ]]; then npm ci --ignore-scripts --no-audit --no-fund; fi
if [[ -z "${IMAGE_URI:-}" ]]; then
  require_command docker
  docker buildx version >/dev/null 2>&1 || { printf 'Docker Buildx is required to build Cloudflare container images.\n' >&2; exit 1; }
fi
CONFIG=.wrangler.deploy.json
SECRETS_FILE=''
trap 'rm -f "$CONFIG"; if [[ -n "$SECRETS_FILE" ]]; then rm -f "$SECRETS_FILE"; fi' EXIT
if [[ -n "${API_TOKEN:-}" ]]; then
  SECRETS_FILE="$(mktemp)"
  chmod 600 "$SECRETS_FILE"
  node --input-type=module - "$SECRETS_FILE" <<'JS'
import fs from 'node:fs'
fs.writeFileSync(process.argv[2], JSON.stringify({ API_TOKEN: process.env.API_TOKEN }))
JS
fi
node --input-type=module <<'JS'
import fs from 'node:fs'
const config = JSON.parse(fs.readFileSync('wrangler.jsonc', 'utf8'))
config.name = process.env.DOCUMENT_OCR_NAME
config.vars.DOCUMENT_OCR_KYC_LANGS = process.env.DOCUMENT_OCR_KYC_LANGS
config.vars.CONTAINER_IDLE_TIMEOUT = process.env.DOCUMENT_OCR_PROFILE === 'warm' ? '1h' : '10m'
config.vars.CONTAINER_INSTANCES = process.env.DOCUMENT_OCR_MAX_INSTANCES || '2'
const count = Number(config.vars.CONTAINER_INSTANCES)
if (!Number.isInteger(count) || count < 1 || count > 100) throw new Error('DOCUMENT_OCR_MAX_INSTANCES must be 1..100')
config.containers[0].max_instances = count
config.containers[0].image_vars.DOCUMENT_OCR_KYC_LANGS = process.env.DOCUMENT_OCR_KYC_LANGS
if (process.env.IMAGE_URI) config.containers[0].image = process.env.IMAGE_URI
fs.writeFileSync('.wrangler.deploy.json', JSON.stringify(config, null, 2))
JS
# A temporary mode-0600 file passes environment secrets without CLI-value leakage.
# Otherwise use existing Wrangler secrets; required-secret validation fails closed.
if [[ -n "$SECRETS_FILE" ]]; then
  node_modules/.bin/wrangler deploy --config "$CONFIG" --secrets-file "$SECRETS_FILE" "$@"
else
  node_modules/.bin/wrangler deploy --config "$CONFIG" "$@"
fi
