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

# Use venv if it exists, otherwise fall back to system python3
VENV="$SCRIPT_DIR/.venv/bin/python3"
PYTHON=$([ -x "$VENV" ] && echo "$VENV" || echo "python3")

exec "$PYTHON" "$SCRIPT_DIR/job_digest.py"
