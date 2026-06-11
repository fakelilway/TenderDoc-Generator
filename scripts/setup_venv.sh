#!/usr/bin/env bash
set -euo pipefail

# Create a reproducible .venv using Python 3.10+ and install backend dependencies.
# Usage: run from repository root: ./scripts/setup_venv.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$REPO_ROOT/.venv"

echo "Using repo root: $REPO_ROOT"

find_python() {
  local candidates=()
  if [ -n "${PYTHON_BIN:-}" ]; then
    candidates+=("$PYTHON_BIN")
  fi
  candidates+=(python3.11 python3.10 python3 python)

  local candidate version major minor
  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi

    version="$($candidate -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
    major="${version%%.*}"
    minor="${version#*.}"
    minor="${minor%%.*}"

    if [ "${major:-0}" -eq 3 ] && [ "${minor:-0}" -ge 10 ]; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

PYTHON_CMD="$(find_python || true)"
if [ -z "$PYTHON_CMD" ]; then
  echo "Python 3.10+ not found. Please install Python 3.10 or 3.11 (Homebrew: brew install python@3.10 or python@3.11)." >&2
  exit 1
fi

PYTHON_VERSION="$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "Using Python interpreter: $PYTHON_CMD ($PYTHON_VERSION)"

if [ "${RESET_VENV:-0}" = "1" ]; then
  echo "Removing existing venv at $VENV_PATH"
  rm -rf "$VENV_PATH"
fi

if [ ! -x "$VENV_PATH/bin/python" ]; then
  echo "Creating venv with $PYTHON_CMD"
  "$PYTHON_CMD" -m venv "$VENV_PATH"
fi
source "$VENV_PATH/bin/activate"
PYTHON_BIN="$VENV_PATH/bin/python"

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  echo "pip not found in venv. Bootstrapping with ensurepip"
  "$PYTHON_BIN" -m ensurepip --upgrade
fi

echo "Upgrading pip"
"$PYTHON_BIN" -m pip install -U pip

echo "Pinning compatible packaging build tools"
"$PYTHON_BIN" -m pip install --force-reinstall "wheel==0.45.0" "packaging==23.2" "setuptools==81.0.0"

echo "Installing backend requirements"
"$PYTHON_BIN" -m pip install -r "$REPO_ROOT/backend/requirements.txt"

echo "Verifying environment"
"$PYTHON_BIN" -m pip check

echo "Done. Activate with: source $VENV_PATH/bin/activate"
echo "Run tests: cd backend && python -m pytest tests/ -q"
