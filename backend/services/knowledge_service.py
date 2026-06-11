from __future__ import annotations

import re
from datetime import date
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
    project_type: str | None = None,
    document_type: str | None = None,
    document_category: str | None = None,
    specialty: str | None = None,
    volume: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    certificate_type: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    sensitivity: str | None = None,
    usage_scope: str | None = None,
    verified_status: str | None = None,
    image_insertable: bool | None = None,
    tags: list[str] | None = None,
    ingestion_mode: str | None = None,
) -> dict[str, object]:
    if not file_bytes:
        raise ValueError("Uploaded knowledge file is empty")

    safe_name = _safe_filename(filename)
    object_name = _knowledge_object_name(safe_name)
    minio_client.upload_file(settings.minio_bucket, file_bytes, object_name)

    mode = ingestion_mode or _default_ingestion_mode(safe_name, document_type)
    metadata = _clean_metadata(
        project_type=project_type,
        document_type=document_type,
        document_category=document_category,
        specialty=specialty,
        volume=volume,
        region=region,
        project_year=project_year,
        owner_type=owner_type,
        owner_name=owner_name,
        certificate_type=certificate_type,
        valid_from=valid_from,
        valid_to=valid_to,
        sensitivity=sensitivity,
        usage_scope=usage_scope,
        verified_status=verified_status,
        image_insertable=image_insertable
        if image_insertable is not None
        else _preview_type(_file_type(safe_name, content_type), safe_name, False)
        == "image",
        tags=tags,
    )
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
    raw_chunks = split_text(text)
    if not raw_chunks and indexing_status in {"structured_evidence", "evidence_only"}:
        summary_text = _evidence_summary_text(safe_name, metadata)
        raw_chunks = [summary_text] if summary_text else []

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
        for index, content in enumerate(raw_chunks)
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
            **_metadata_summary(row[4] or {}),
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
        if metadata.get("image_insertable") is False:
            continue
        if _metadata_is_expired(metadata):
            continue
        candidates.append(
            {
                "document_id": int(row[0]),
                "file_name": file_name,
                "file_path": row[2],
                "file_type": file_type,
                **_metadata_summary(metadata),
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
        str(metadata.get("owner_name") or "").strip(),
        str(metadata.get("certificate_type") or "").strip(),
        str(metadata.get("document_category") or "").strip(),
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
    for key in (
        "project_type",
        "document_type",
        "document_category",
        "specialty",
        "volume",
        "region",
        "project_year",
        "owner_type",
        "owner_name",
        "certificate_type",
        "sensitivity",
        "usage_scope",
        "verified_status",
    ):
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


def _evidence_summary_text(file_name: str, metadata: dict) -> str:
    labels = {
        "document_category": "资料类别",
        "document_type": "细分类型",
        "project_type": "项目类型",
        "specialty": "专业",
        "volume": "所属卷册",
        "region": "地区",
        "project_year": "年份",
        "owner_type": "归属类型",
        "owner_name": "归属名称",
        "certificate_type": "证件/证明",
        "valid_from": "有效期起",
        "valid_to": "有效期止",
        "sensitivity": "敏感级别",
        "usage_scope": "使用范围",
        "verified_status": "核验状态",
    }
    lines = [f"资料名称：{Path(file_name).stem}"]
    for key, label in labels.items():
        value = metadata.get(key)
        if value:
            lines.append(f"{label}：{value}")
    tags = metadata.get("tags") or []
    if isinstance(tags, list) and tags:
        lines.append("标签：" + "、".join(str(tag) for tag in tags if str(tag).strip()))
    if metadata.get("image_insertable") is True:
        lines.append("图片用途：允许作为标书插图候选")
    return "\n".join(lines)


def rename_knowledge_document(
    document_id: int,
    title: str,
    project_type: str | None = None,
    document_type: str | None = None,
    document_category: str | None = None,
    specialty: str | None = None,
    volume: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    certificate_type: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    sensitivity: str | None = None,
    usage_scope: str | None = None,
    verified_status: str | None = None,
    image_insertable: bool | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    safe_title = _safe_title(title)
    if not safe_title:
        raise ValueError("Knowledge document title is required")

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT metadata_json
                FROM documents
                WHERE id = %s AND project_id IS NULL
                """,
                (document_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Knowledge document {document_id} was not found")
            metadata = _merge_metadata(
                current[0] or {},
                project_type=project_type,
                document_type=document_type,
                document_category=document_category,
                specialty=specialty,
                volume=volume,
                region=region,
                project_year=project_year,
                owner_type=owner_type,
                owner_name=owner_name,
                certificate_type=certificate_type,
                valid_from=valid_from,
                valid_to=valid_to,
                sensitivity=sensitivity,
                usage_scope=usage_scope,
                verified_status=verified_status,
                image_insertable=image_insertable,
                tags=tags,
            )
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
        **_metadata_summary(row[4] or {}),
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
    *,
    project_type: str | None = None,
    document_type: str | None = None,
    document_category: str | None = None,
    specialty: str | None = None,
    volume: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    certificate_type: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    sensitivity: str | None = None,
    usage_scope: str | None = None,
    verified_status: str | None = None,
    image_insertable: bool | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    clean_tags = [
        re.sub(r"\s+", " ", tag).strip() for tag in (tags or []) if str(tag).strip()
    ]
    metadata: dict[str, object] = {"tags": sorted(set(clean_tags))}
    for key, value in {
        "project_type": project_type,
        "document_type": document_type,
        "document_category": document_category,
        "specialty": specialty,
        "volume": volume,
        "region": region,
        "owner_type": owner_type,
        "owner_name": owner_name,
        "certificate_type": certificate_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "sensitivity": sensitivity,
        "usage_scope": usage_scope,
        "verified_status": verified_status,
    }.items():
        if value and str(value).strip():
            metadata[key] = re.sub(r"\s+", " ", str(value)).strip()
    if project_year:
        metadata["project_year"] = int(project_year)
    if image_insertable is not None:
        metadata["image_insertable"] = bool(image_insertable)
    return metadata


def _merge_metadata(existing: dict, **updates) -> dict[str, object]:
    merged = dict(existing or {})
    clean_updates = _clean_metadata(**updates)
    for key, value in clean_updates.items():
        if key == "tags" and updates.get("tags") is None:
            continue
        merged[key] = value
    return merged


def _metadata_summary(metadata: dict) -> dict[str, object]:
    return {
        "project_type": metadata.get("project_type"),
        "document_type": metadata.get("document_type"),
        "document_category": metadata.get("document_category"),
        "specialty": metadata.get("specialty"),
        "volume": metadata.get("volume"),
        "region": metadata.get("region"),
        "project_year": metadata.get("project_year"),
        "owner_type": metadata.get("owner_type"),
        "owner_name": metadata.get("owner_name"),
        "certificate_type": metadata.get("certificate_type"),
        "valid_from": metadata.get("valid_from"),
        "valid_to": metadata.get("valid_to"),
        "sensitivity": metadata.get("sensitivity"),
        "usage_scope": metadata.get("usage_scope"),
        "verified_status": metadata.get("verified_status"),
        "image_insertable": metadata.get("image_insertable"),
        "tags": metadata.get("tags", []),
        "ingestion_mode": metadata.get("ingestion_mode"),
        "indexing_status": metadata.get("indexing_status"),
        "extraction_message": metadata.get("extraction_message"),
    }


def _metadata_is_expired(metadata: dict) -> bool:
    if str(metadata.get("verified_status") or "").strip() == "已过期":
        return True
    valid_to = str(metadata.get("valid_to") or "").strip()
    if not valid_to:
        return False
    try:
        return date.fromisoformat(valid_to) < date.today()
    except ValueError:
        return False
