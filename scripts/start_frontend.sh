#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  "$REPO_ROOT/scripts/setup_frontend.sh"
fi

cd "$FRONTEND_DIR"
export BACKEND_API_BASE_URL="${BACKEND_API_BASE_URL:-http://localhost:8000}"

if command -v pnpm >/dev/null 2>&1; then
  exec pnpm dev -H 0.0.0.0 -p "${FRONTEND_PORT:-3000}"
fi

exec npm run dev -- -H 0.0.0.0 -p "${FRONTEND_PORT:-3000}"
