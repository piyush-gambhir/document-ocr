#!/usr/bin/env bash
# Shared validation only. Sourcing this file performs no cloud operations.
set -euo pipefail
require_command() {
  command -v "$1" >/dev/null 2>&1 || { printf 'Required command is missing: %s\n' "$1" >&2; exit 1; }
}
hosting_defaults() {
  export DOCUMENT_OCR_NAME="${DOCUMENT_OCR_NAME:-document-ocr}"
  export DOCUMENT_OCR_PROFILE="${DOCUMENT_OCR_PROFILE:-economy}"
  export DOCUMENT_OCR_KYC_LANGS="${DOCUMENT_OCR_KYC_LANGS:-en}"
  [[ "$DOCUMENT_OCR_NAME" =~ ^[a-z][a-z0-9-]{0,39}$ ]] || { printf 'Invalid DOCUMENT_OCR_NAME\n' >&2; exit 1; }
  case "$DOCUMENT_OCR_PROFILE" in economy|warm) ;; *) printf 'Profile must be economy or warm\n' >&2; exit 1;; esac
  [[ "$DOCUMENT_OCR_KYC_LANGS" =~ ^(en|latin|devanagari|ka|ta|te)(,(en|latin|devanagari|ka|ta|te)){0,3}$ ]] || { printf 'Invalid DOCUMENT_OCR_KYC_LANGS (up to four supported languages)\n' >&2; exit 1; }
}
