#!/usr/bin/env bash
set -euo pipefail

# Create a reproducible .venv using Python 3.11 and install backend dependencies.
# Usage: run from repository root: ./scripts/setup_venv.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$REPO_ROOT/.venv"

echo "Using repo root: $REPO_ROOT"

if ! command -v python3.11 >/dev/null 2>&1; then
  echo "python3.11 not found. Please install Python 3.11 (Homebrew: brew install python@3.11)" >&2
  exit 1
fi

if [ "${RESET_VENV:-0}" = "1" ]; then
  echo "Removing existing venv at $VENV_PATH"
  rm -rf "$VENV_PATH"
fi

if [ ! -x "$VENV_PATH/bin/python" ]; then
  echo "Creating venv with python3.11"
  python3.11 -m venv "$VENV_PATH"
fi
source "$VENV_PATH/bin/activate"

echo "Upgrading pip, setuptools, wheel"
pip install -U pip setuptools wheel

echo "Installing backend requirements"
pip install -r "$REPO_ROOT/backend/requirements.txt"

# Ensure the packaging/wheel/setuptools trio is compatible with pinned libs (torch/langchain-core)
echo "Ensuring compatible packaging/wheel/setuptools versions"
pip install --force-reinstall "wheel==0.45.0" "packaging==23.2" "setuptools==81.0.0"

echo "Verifying environment"
pip check

echo "Done. Activate with: source $VENV_PATH/bin/activate"
echo "Run tests: cd backend && python -m pytest tests/ -q"
