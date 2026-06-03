#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  "$REPO_ROOT/scripts/setup_venv.sh"
fi

if [ ! -f "$REPO_ROOT/backend/.env" ]; then
  cp "$REPO_ROOT/backend/.env.example" "$REPO_ROOT/backend/.env"
  echo "Created backend/.env. Add OPENROUTER_API_KEY for live AI calls."
fi

cd "$REPO_ROOT/backend"
exec "$REPO_ROOT/.venv/bin/python" -m uvicorn api.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT:-8000}"
