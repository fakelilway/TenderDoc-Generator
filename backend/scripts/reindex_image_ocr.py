"""Re-index existing knowledge-base image evidence with OCR (M16).

Image certs uploaded before OCR was wired only have a tag-summary chunk. This
re-runs them through ``index_uploaded_knowledge`` (which now OCRs images), then
deletes the old document. Idempotent: skips docs already marked ``ocr_extracted``.

用法：PYTHONPATH=backend .venv/bin/python backend/scripts/reindex_image_ocr.py [--apply]
不带 --apply 只列出将处理的文档（dry-run）。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.config import get_settings  # noqa: E402
from rag.vector_store import _connect  # noqa: E402
from services.knowledge_service import (  # noqa: E402
    delete_knowledge_document,
    index_uploaded_knowledge,
)
from utils.minio_client import minio_client  # noqa: E402

_IMAGE_RE = r"\.(jpg|jpeg|png)$"
_META_FIELDS = (
    "project_type", "document_type", "document_category", "specialty", "volume",
    "region", "project_year", "owner_type", "owner_name", "certificate_type",
    "valid_from", "valid_to", "sensitivity", "usage_scope", "verified_status",
    "image_insertable", "tags", "ingestion_mode",
)


def _image_docs() -> list[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, file_name, file_path, metadata_json FROM documents
                    WHERE project_id IS NULL AND lower(file_name) ~ '{_IMAGE_RE}'
                    ORDER BY id"""
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "file_name": r[1], "file_path": r[2], "metadata": r[3] or {}}
        for r in rows
    ]


def main() -> None:
    apply = "--apply" in sys.argv
    bucket = get_settings().minio_bucket
    docs = _image_docs()
    todo = [d for d in docs if not d["metadata"].get("ocr_extracted")]
    print(f"图片文档 {len(docs)} 个，待 OCR 重索引 {len(todo)} 个"
          + ("" if apply else "（dry-run，加 --apply 执行）"))
    for d in todo:
        print(f"  - id={d['id']} {d['file_name'][:48]}")
    if not apply:
        return

    for d in todo:
        try:
            data = minio_client.download_bytes(bucket, d["file_path"])
            kwargs = {k: d["metadata"].get(k) for k in _META_FIELDS}
            result = index_uploaded_knowledge(data, d["file_name"], **kwargs)
            delete_knowledge_document(d["id"])
            print(f"  ✓ id={d['id']} → new id={result['document_id']} "
                  f"status={result['indexing_status']}")
        except Exception as error:  # keep going on per-doc failure
            print(f"  ✗ id={d['id']} 失败: {type(error).__name__}: {str(error)[:80]}")


if __name__ == "__main__":
    main()
