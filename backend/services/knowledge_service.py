from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from core.config import settings
from rag.indexer import KnowledgeChunk, split_text
from rag.vector_store import store_knowledge_chunks
from utils.file_parser import extract_text
from utils.minio_client import minio_client


def _safe_filename(filename: str) -> str:
    basename = Path(filename or "knowledge.txt").name
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", basename, flags=re.UNICODE)
    return cleaned.strip("._") or "knowledge.txt"


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
