from __future__ import annotations

import threading
from typing import Callable

from psycopg2.extras import Json, RealDictCursor, execute_values

from core.config import settings
from core.db import get_db_connection
from rag.embeddings import embed_texts
from rag.indexer import KnowledgeChunk


EmbedTexts = Callable[[list[str]], list[list[float]]]

_METADATA_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS knowledge_chunks_metadata_gin
ON knowledge_chunks USING GIN (metadata)
"""

_metadata_index_lock = threading.Lock()
_metadata_index_ready = False


def _connect():
    """Pooled connection context manager; commits are the caller's job."""
    return get_db_connection()


def ensure_metadata_index() -> None:
    """Schema init: GIN index so metadata-filtered vector search can use an index.

    Idempotent and executed once per process.
    """
    global _metadata_index_ready
    if _metadata_index_ready:
        return
    with _metadata_index_lock:
        if _metadata_index_ready:
            return
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_METADATA_INDEX_SQL)
            conn.commit()
        _metadata_index_ready = True


def format_vector(vector: list[float]) -> str:
    if len(vector) != settings.embedding_dimension:
        message = (
            f"Expected vector dimension {settings.embedding_dimension}, "
            f"got {len(vector)}"
        )
        raise ValueError(message)
    return "[" + ",".join(f"{value:.10f}" for value in vector) + "]"


def store_knowledge_chunks(
    file_name: str,
    file_path: str,
    file_type: str,
    chunks: list[KnowledgeChunk],
    embedder: EmbedTexts = embed_texts,
    metadata: dict | None = None,
) -> dict[str, object]:
    embeddings = embedder([chunk.content for chunk in chunks]) if chunks else []
    if chunks and len(embeddings) != len(chunks):
        raise ValueError("Embedding count does not match chunk count")

    ensure_metadata_index()

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO documents
                    (project_id, file_name, file_path, file_type, metadata_json)
                VALUES (NULL, %s, %s, %s, %s)
                RETURNING id
                """,
                (file_name, file_path, file_type, Json(metadata or {})),
            )
            document_id = cursor.fetchone()["id"]

            chunk_ids: list[int] = []
            if chunks:
                rows = execute_values(
                    cursor,
                    """
                    INSERT INTO knowledge_chunks
                        (document_id, content, metadata, embedding)
                    VALUES %s
                    RETURNING id
                    """,
                    [
                        (
                            document_id,
                            chunk.content,
                            Json(chunk.metadata),
                            format_vector(embedding),
                        )
                        for chunk, embedding in zip(chunks, embeddings)
                    ],
                    template="(%s, %s, %s, %s::vector)",
                    fetch=True,
                )
                chunk_ids = [row["id"] for row in rows]
        conn.commit()

    return {"document_id": document_id, "chunk_ids": chunk_ids}
