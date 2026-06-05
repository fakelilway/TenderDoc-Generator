from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from core.config import settings
from rag.indexer import KnowledgeChunk, split_text
from rag.vector_store import _connect, store_knowledge_chunks
from utils.file_parser import extract_text
from utils.minio_client import minio_client


def _safe_filename(filename: str) -> str:
    basename = Path(filename or "knowledge.txt").name
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", basename, flags=re.UNICODE)
    return cleaned.strip("._") or "knowledge.txt"


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[/\\\x00-\x1f]+", "_", title or "").strip()
    return cleaned[:180]


def _knowledge_object_name(filename: str) -> str:
    return f"knowledge/{uuid4().hex}_{_safe_filename(filename)}"


def _file_type(filename: str, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    if content_type and "/" in content_type:
        return content_type.rsplit("/", 1)[-1]
    return "unknown"


def index_uploaded_knowledge(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> dict[str, object]:
    if not file_bytes:
        raise ValueError("Uploaded knowledge file is empty")

    safe_name = _safe_filename(filename)
    object_name = _knowledge_object_name(safe_name)
    minio_client.upload_file(settings.minio_bucket, file_bytes, object_name)

    text = extract_text(file_bytes, filename=safe_name, content_type=content_type)
    chunks = [
        KnowledgeChunk(
            content=content,
            metadata={
                "source_path": object_name,
                "file_name": safe_name,
                "file_type": _file_type(safe_name, content_type),
                "chunk_index": index,
            },
        )
        for index, content in enumerate(split_text(text))
    ]
    stored = store_knowledge_chunks(
        file_name=safe_name,
        file_path=object_name,
        file_type=_file_type(safe_name, content_type),
        chunks=chunks,
    )
    return {
        "document_id": stored["document_id"],
        "chunk_ids": stored["chunk_ids"],
        "file_path": object_name,
    }


def list_knowledge_documents(limit: int = 50) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("limit must be positive")

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    documents.id AS document_id,
                    documents.file_name,
                    documents.file_path,
                    documents.file_type,
                    documents.created_at,
                    COUNT(knowledge_chunks.id) AS chunk_count
                FROM documents
                LEFT JOIN knowledge_chunks
                    ON knowledge_chunks.document_id = documents.id
                WHERE documents.project_id IS NULL
                GROUP BY
                    documents.id,
                    documents.file_name,
                    documents.file_path,
                    documents.file_type,
                    documents.created_at
                ORDER BY documents.created_at DESC, documents.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

    return [
        {
            "document_id": int(row[0]),
            "file_name": row[1],
            "file_path": row[2],
            "file_type": row[3],
            "created_at": row[4].isoformat(),
            "chunk_count": int(row[5]),
        }
        for row in rows
    ]


def rename_knowledge_document(document_id: int, title: str) -> dict[str, object]:
    safe_title = _safe_title(title)
    if not safe_title:
        raise ValueError("Knowledge document title is required")

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE documents
                SET file_name = %s
                WHERE id = %s AND project_id IS NULL
                RETURNING id, file_name, file_path, file_type, created_at
                """,
                (safe_title, document_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Knowledge document {document_id} was not found")

            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{file_name}',
                    to_jsonb(%s::text),
                    true
                )
                WHERE document_id = %s
                """,
                (safe_title, document_id),
            )

            cursor.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = %s",
                (document_id,),
            )
            chunk_count = int(cursor.fetchone()[0])

    return {
        "document_id": int(row[0]),
        "file_name": row[1],
        "file_path": row[2],
        "file_type": row[3],
        "created_at": row[4].isoformat(),
        "chunk_count": chunk_count,
    }


def delete_knowledge_document(document_id: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM documents
                WHERE id = %s AND project_id IS NULL
                RETURNING file_path
                """,
                (document_id,),
            )
            row = cursor.fetchone()

    if not row:
        raise ValueError(f"Knowledge document {document_id} was not found")

    object_name = row[0]
    if object_name:
        try:
            minio_client.remove_file(settings.minio_bucket, str(object_name))
        except Exception:
            # The database is the source of truth for retrieval; missing object cleanup
            # should not keep a deleted document searchable.
            pass
