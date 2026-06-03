#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$REPO_ROOT/scripts/init_db.sh"

cleanup() {
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$REPO_ROOT/scripts/start_backend.sh" &
BACKEND_PID=$!

echo "Waiting for backend"
until curl -fsS http://localhost:${BACKEND_PORT:-8000}/health >/dev/null 2>&1; do
  sleep 1
done

"$REPO_ROOT/scripts/start_frontend.sh" &
FRONTEND_PID=$!

echo
echo "TenderDoc local dev is running"
echo "Frontend: http://localhost:${FRONTEND_PORT:-3000}"
echo "Backend API docs: http://localhost:${BACKEND_PORT:-8000}/docs"
echo "Press Ctrl+C to stop backend and frontend."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
