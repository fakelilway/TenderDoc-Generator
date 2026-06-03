#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

if ! command -v node >/dev/null 2>&1; then
  echo "node not found. Install Node.js 20+ first." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

if command -v pnpm >/dev/null 2>&1; then
  echo "Installing frontend dependencies with pnpm"
  if [ -f pnpm-lock.yaml ]; then
    pnpm install --frozen-lockfile --registry="${NPM_REGISTRY:-https://registry.npmmirror.com}"
  else
    pnpm install --registry="${NPM_REGISTRY:-https://registry.npmmirror.com}"
  fi
elif command -v npm >/dev/null 2>&1; then
  echo "Installing frontend dependencies with npm"
  npm install --registry="${NPM_REGISTRY:-https://registry.npmmirror.com}"
else
  echo "Neither pnpm nor npm was found. Install Node.js 20+ first." >&2
  exit 1
fi
