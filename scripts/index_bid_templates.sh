#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:${BACKEND_PORT:-8000}}"

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 /path/to/投标文件1.PDF [/path/to/投标文件2.PDF ...]" >&2
  echo "Example: $0 \"/Users/mingbai/Desktop/新建文件夹/标书/1投标文件.PDF\" \"/Users/mingbai/Desktop/新建文件夹/标书/2投标文件.PDF\"" >&2
  exit 1
fi

for file_path in "$@"; do
  if [ ! -f "$file_path" ]; then
    echo "Template file not found: $file_path" >&2
    exit 1
  fi

  echo "Indexing bid template: $file_path"
  curl -fsS \
    --max-time "${UPLOAD_TIMEOUT_SECONDS:-900}" \
    -F "file=@${file_path}" \
    "$BACKEND_URL/api/knowledge/upload"
  echo
done

echo "Bid templates indexed into the local knowledge base."
