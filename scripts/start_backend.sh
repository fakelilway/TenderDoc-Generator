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
# --reload 在跑真实生成时是有害的:生成是后台 daemon 线程,任何 .py 改动都会让
# uvicorn 重启、把在跑的生成线程杀掉、状态冻住。跑真实生成请用 BACKEND_NO_RELOAD=1。
RELOAD_ARG="--reload"
if [ "${BACKEND_NO_RELOAD:-0}" = "1" ]; then
  RELOAD_ARG=""
fi
exec "$REPO_ROOT/.venv/bin/python" -m uvicorn api.main:app $RELOAD_ARG --host 0.0.0.0 --port "${BACKEND_PORT:-8000}"
