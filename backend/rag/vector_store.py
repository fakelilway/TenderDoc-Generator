from __future__ import annotations

from typing import Callable

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from core.config import settings
from rag.embeddings import embed_texts
from rag.indexer import KnowledgeChunk


EmbedTexts = Callable[[list[str]], list[list[float]]]


def _connect():
    if settings.database_url:
        return psycopg2.connect(settings.database_url)

    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


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
    if not chunks:
        raise ValueError("No chunks to store")

    embeddings = embedder([chunk.content for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise ValueError("Embedding count does not match chunk count")

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
            for chunk, embedding in zip(chunks, embeddings):
                cursor.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (document_id, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s::vector)
                    RETURNING id
                    """,
                    (
                        document_id,
                        chunk.content,
                        Json(chunk.metadata),
                        format_vector(embedding),
                    ),
                )
                chunk_ids.append(cursor.fetchone()["id"])

    return {"document_id": document_id, "chunk_ids": chunk_ids}
