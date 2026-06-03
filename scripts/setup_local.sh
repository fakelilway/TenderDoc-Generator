#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$REPO_ROOT/backend/.env" ]; then
  echo "Creating backend/.env from backend/.env.example"
  cp "$REPO_ROOT/backend/.env.example" "$REPO_ROOT/backend/.env"
  echo "Edit backend/.env and set OPENROUTER_API_KEY before running live AI flows."
fi

"$REPO_ROOT/scripts/setup_venv.sh"
"$REPO_ROOT/scripts/setup_frontend.sh"
"$REPO_ROOT/scripts/init_db.sh"

echo
echo "Setup complete."
echo "Start everything with: ./scripts/dev_local.sh"
