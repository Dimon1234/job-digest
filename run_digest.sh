#!/bin/bash
# Wrapper — loads .env and runs the digest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] $ENV_FILE not found" >&2
  exit 1
fi

# Load env vars (skip comments and blank lines)
set -o allexport
# shellcheck source=/dev/null
source "$ENV_FILE"
set +o allexport

exec python3 "$SCRIPT_DIR/job_digest.py"
