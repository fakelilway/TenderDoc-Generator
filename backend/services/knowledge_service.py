from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from core.config import settings
from rag.indexer import KnowledgeChunk, split_text
from psycopg2.extras import Json

from rag.vector_store import _connect, store_knowledge_chunks
from utils.file_parser import IMAGE_EXTENSIONS, extract_text
from utils.minio_client import minio_client


PREVIEW_EXPIRY_SECONDS = 900
PREVIEW_TEXT_LIMIT = 20000
IMAGE_FILE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}


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


def _default_ingestion_mode(filename: str, document_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    normalized_type = (document_type or "").lower()
    sensitive_keywords = (
        "身份证",
        "社保",
        "开户",
        "银行卡",
        "id_card",
        "social_security",
        "bank",
    )
    if any(keyword in normalized_type for keyword in sensitive_keywords):
        return "structured_evidence"
    if suffix in IMAGE_EXTENSIONS:
        return "structured_evidence"
    return "rag_text"


def index_uploaded_knowledge(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    document_type: str | None = None,
    specialty: str | None = None,
    project_year: int | None = None,
    tags: list[str] | None = None,
    ingestion_mode: str | None = None,
) -> dict[str, object]:
    if not file_bytes:
        raise ValueError("Uploaded knowledge file is empty")

    safe_name = _safe_filename(filename)
    object_name = _knowledge_object_name(safe_name)
    minio_client.upload_file(settings.minio_bucket, file_bytes, object_name)

    mode = ingestion_mode or _default_ingestion_mode(safe_name, document_type)
    metadata = _clean_metadata(document_type, specialty, project_year, tags)
    text = ""
    extraction_message = ""
    if mode == "rag_text":
        try:
            text = extract_text(
                file_bytes, filename=safe_name, content_type=content_type
            )
        except ValueError as error:
            mode = "evidence_only"
            extraction_message = str(error)
    chunks = split_text(text)
    indexing_status = "indexed" if chunks else "evidence_only"
    if mode == "structured_evidence":
        indexing_status = "structured_evidence"
    metadata = {
        **metadata,
        "ingestion_mode": mode,
        "indexing_status": indexing_status,
        "extraction_message": extraction_message,
    }
    chunks = [
        KnowledgeChunk(
            content=content,
            metadata={
                "source_path": object_name,
                "file_name": safe_name,
                "file_type": _file_type(safe_name, content_type),
                "chunk_index": index,
                **metadata,
            },
        )
        for index, content in enumerate(split_text(text))
    ]
    stored = store_knowledge_chunks(
        file_name=safe_name,
        file_path=object_name,
        file_type=_file_type(safe_name, content_type),
        chunks=chunks,
        metadata=metadata,
    )
    return {
        "document_id": stored["document_id"],
        "chunk_ids": stored["chunk_ids"],
        "file_path": object_name,
        "indexing_status": indexing_status,
        "extraction_message": extraction_message,
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
                    documents.metadata_json,
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
                    documents.metadata_json,
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
            "document_type": (row[4] or {}).get("document_type"),
            "specialty": (row[4] or {}).get("specialty"),
            "project_year": (row[4] or {}).get("project_year"),
            "tags": (row[4] or {}).get("tags", []),
            "ingestion_mode": (row[4] or {}).get("ingestion_mode"),
            "indexing_status": (row[4] or {}).get("indexing_status"),
            "extraction_message": (row[4] or {}).get("extraction_message"),
            "created_at": row[5].isoformat(),
            "chunk_count": int(row[6]),
        }
        for row in rows
    ]


def get_knowledge_document_preview(document_id: int) -> dict[str, object]:
    row = _fetch_knowledge_document_row(document_id)
    file_name = str(row["file_name"])
    file_type = str(row.get("file_type") or "").lower()
    file_path = str(row.get("file_path") or "")
    metadata = row.get("metadata_json") or {}
    content = _joined_chunk_text(document_id)
    preview_type = _preview_type(file_type, file_name, bool(content))
    preview_url = None
    download_url = None

    if file_path:
        preview_url = minio_client.get_presigned_url(
            settings.minio_bucket,
            file_path,
            expiry=PREVIEW_EXPIRY_SECONDS,
        )
        download_url = minio_client.get_presigned_url(
            settings.minio_bucket,
            file_path,
            expiry=PREVIEW_EXPIRY_SECONDS,
            response_filename=file_name,
        )

    return {
        "document_id": int(row["document_id"]),
        "file_name": file_name,
        "file_type": file_type,
        "preview_type": preview_type,
        "content": content,
        "preview_url": preview_url,
        "download_url": download_url,
        "expires_in": PREVIEW_EXPIRY_SECONDS,
        "indexing_status": metadata.get("indexing_status"),
        "extraction_message": metadata.get("extraction_message"),
    }


def get_knowledge_document_file_bytes(document_id: int) -> bytes:
    row = _fetch_knowledge_document_row(document_id)
    file_name = str(row["file_name"])
    file_type = str(row.get("file_type") or "").lower()
    file_path = str(row.get("file_path") or "")
    if _preview_type(file_type, file_name, has_text=False) != "image":
        raise ValueError(f"Knowledge document {document_id} is not an image")
    if not file_path:
        raise ValueError(f"Knowledge document {document_id} has no stored file")
    return minio_client.download_bytes(settings.minio_bucket, file_path)


def list_knowledge_image_references(
    query: str = "",
    limit: int = 12,
) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, file_name, file_path, file_type, metadata_json
                FROM documents
                WHERE project_id IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 200
                """
            )
            rows = cursor.fetchall()

    candidates: list[dict[str, object]] = []
    for row in rows:
        metadata = row[4] or {}
        file_type = str(row[3] or "").lower()
        file_name = str(row[1] or "")
        if _preview_type(file_type, file_name, has_text=False) != "image":
            continue
        candidates.append(
            {
                "document_id": int(row[0]),
                "file_name": file_name,
                "file_path": row[2],
                "file_type": file_type,
                "document_type": metadata.get("document_type"),
                "specialty": metadata.get("specialty"),
                "project_year": metadata.get("project_year"),
                "tags": metadata.get("tags", []),
                "caption": _image_caption(file_name, metadata),
                "match_score": _image_reference_score(query, file_name, metadata),
            }
        )

    return sorted(
        candidates,
        key=lambda item: (int(item["match_score"]), int(item["document_id"])),
        reverse=True,
    )[:limit]


def _fetch_knowledge_document_row(document_id: int) -> dict[str, object]:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id AS document_id,
                    file_name,
                    file_path,
                    file_type,
                    metadata_json
                FROM documents
                WHERE id = %s AND project_id IS NULL
                """,
                (document_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ValueError(f"Knowledge document {document_id} was not found")
    return {
        "document_id": row[0],
        "file_name": row[1],
        "file_path": row[2],
        "file_type": row[3],
        "metadata_json": row[4] or {},
    }


def _joined_chunk_text(document_id: int) -> str:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT content
                FROM knowledge_chunks
                WHERE document_id = %s
                ORDER BY id
                """,
                (document_id,),
            )
            rows = cursor.fetchall()
    text = "\n\n".join(str(row[0]).strip() for row in rows if str(row[0]).strip())
    return text[:PREVIEW_TEXT_LIMIT]


def _preview_type(file_type: str, file_name: str, has_text: bool) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    normalized = (file_type or suffix).lower()
    mime_major = normalized.split("/", 1)[0] if "/" in normalized else ""
    subtype = normalized.rsplit("/", 1)[-1]
    candidates = {normalized, subtype, suffix}
    if mime_major == "image" or candidates & IMAGE_FILE_TYPES:
        return "image"
    if has_text or mime_major == "text" or candidates & {"txt", "md", "markdown"}:
        return "text"
    if "pdf" in candidates:
        return "pdf"
    return "file"


def _image_caption(file_name: str, metadata: dict) -> str:
    parts = [
        str(metadata.get("document_type") or "").strip(),
        str(metadata.get("specialty") or "").strip(),
        str(metadata.get("project_year") or "").strip(),
    ]
    tags = metadata.get("tags") or []
    if isinstance(tags, list):
        parts.extend(str(tag).strip() for tag in tags[:3])
    meaningful = [part for part in parts if part]
    stem = Path(file_name).stem
    return " / ".join(meaningful) if meaningful else stem


def _image_reference_score(query: str, file_name: str, metadata: dict) -> int:
    haystack_parts = [file_name]
    for key in ("document_type", "specialty", "project_year"):
        value = metadata.get(key)
        if value:
            haystack_parts.append(str(value))
    tags = metadata.get("tags") or []
    if isinstance(tags, list):
        haystack_parts.extend(str(tag) for tag in tags)
    haystack = " ".join(haystack_parts)
    tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", query.lower()))
    score = sum(1 for token in tokens if token in haystack.lower())
    priority_keywords = (
        "营业执照",
        "资质证书",
        "安全生产许可证",
        "建造师",
        "身份证",
        "建安",
        "交安",
        "职称",
        "社保",
        "业绩",
    )
    score += sum(3 for keyword in priority_keywords if keyword in haystack)
    return score


def rename_knowledge_document(
    document_id: int,
    title: str,
    document_type: str | None = None,
    specialty: str | None = None,
    project_year: int | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    safe_title = _safe_title(title)
    if not safe_title:
        raise ValueError("Knowledge document title is required")

    metadata = _clean_metadata(document_type, specialty, project_year, tags)
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE documents
                SET file_name = %s,
                    metadata_json = %s
                WHERE id = %s AND project_id IS NULL
                RETURNING id, file_name, file_path, file_type, metadata_json, created_at
                """,
                (safe_title, Json(metadata), document_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Knowledge document {document_id} was not found")

            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET metadata = COALESCE(metadata, '{}'::jsonb)
                    || jsonb_build_object('file_name', %s::text)
                    || %s::jsonb
                WHERE document_id = %s
                """,
                (safe_title, Json(metadata), document_id),
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
        "document_type": (row[4] or {}).get("document_type"),
        "specialty": (row[4] or {}).get("specialty"),
        "project_year": (row[4] or {}).get("project_year"),
        "tags": (row[4] or {}).get("tags", []),
        "ingestion_mode": (row[4] or {}).get("ingestion_mode"),
        "indexing_status": (row[4] or {}).get("indexing_status"),
        "extraction_message": (row[4] or {}).get("extraction_message"),
        "created_at": row[5].isoformat(),
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


def _clean_metadata(
    document_type: str | None,
    specialty: str | None,
    project_year: int | None,
    tags: list[str] | None,
) -> dict[str, object]:
    clean_tags = [
        re.sub(r"\s+", " ", tag).strip() for tag in (tags or []) if str(tag).strip()
    ]
    metadata: dict[str, object] = {"tags": sorted(set(clean_tags))}
    if document_type and document_type.strip():
        metadata["document_type"] = document_type.strip()
    if specialty and specialty.strip():
        metadata["specialty"] = specialty.strip()
    if project_year:
        metadata["project_year"] = int(project_year)
    return metadata
