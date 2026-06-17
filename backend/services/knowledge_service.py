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
    project_id: int | None = None,
    extra_metadata: dict | None = None,
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
    # Image evidence (公司/人员证件 等) is OCR'd even in evidence/structured modes
    # so the cert text (信用代码/资质等级/有效期/法定代表人 等) becomes searchable,
    # while the file stays image-insertable as a 证件扫描件.
    is_image = Path(safe_name).suffix.lower() in IMAGE_EXTENSIONS
    if mode == "rag_text" or is_image:
        try:
            text = extract_text(
                file_bytes, filename=safe_name, content_type=content_type
            )
        except ValueError as error:
            if mode == "rag_text":
                mode = "evidence_only"
            extraction_message = str(error)
    ocr_chunks = split_text(text)
    has_ocr = bool(ocr_chunks)
    indexing_status = "indexed" if ocr_chunks else "evidence_only"
    if mode == "structured_evidence":
        indexing_status = "structured_evidence"
    metadata = {
        **metadata,
        "ingestion_mode": mode,
        "indexing_status": indexing_status,
        "extraction_message": extraction_message,
    }
    # Always keep the structured tag-summary chunk for filtering/search; for image
    # evidence we additionally index the OCR text so cert content is searchable.
    raw_chunks = list(ocr_chunks)
    if is_image or indexing_status in {"structured_evidence", "evidence_only"}:
        summary_text = _evidence_summary_text(safe_name, metadata)
        if summary_text:
            raw_chunks = [summary_text, *ocr_chunks]
    metadata = {**metadata, "ocr_extracted": has_ocr}
    if project_id is not None:
        # M23 本项目专用技术材料:project_id 既写 documents 真列(随项目级联删),也
        # 冗余进 metadata —— 检索按 metadata->>'project_id' 过滤(走 GIN、免 JOIN),
        # 把"本项目材料 ∪ 全局库"喂给技术卷,而全局库视图仍只看 project_id IS NULL。
        metadata = {**metadata, "project_id": project_id}
    if extra_metadata:
        # ② 本项目插入图等:target_section/caption 等自定义字段(供生成时按节插图)。
        metadata = {**metadata, **{k: v for k, v in extra_metadata.items() if v is not None}}

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
        project_id=project_id,
    )
    return {
        "document_id": stored["document_id"],
        "chunk_ids": stored["chunk_ids"],
        "file_path": object_name,
        "indexing_status": indexing_status,
        "extraction_message": extraction_message,
    }


def list_knowledge_documents(
    limit: int = 50,
    category: str | None = None,
    search: str | None = None,
) -> list[dict[str, object]]:
    """List knowledge-base documents, optionally filtered by category/search.

    Filtering is essential now the KB holds thousands of docs: an unfiltered
    "most-recent N" can't surface 公司证件/人员证件 once 业绩 was imported last.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    filters = ["documents.project_id IS NULL"]
    params: list[object] = []
    if category:
        filters.append("documents.metadata_json->>'document_category' = %s")
        params.append(category)
    if search:
        filters.append(
            "(documents.file_name ILIKE %s"
            " OR documents.metadata_json->>'owner_name' ILIKE %s"
            " OR documents.metadata_json->>'certificate_type' ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like])
    where_clause = " AND ".join(filters)

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
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
                WHERE {where_clause}
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
                [*params, limit],
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


def count_documents_by_category() -> dict[str, int]:
    """每个资料类别的文档数(供前端分类标签显示数量),含 total。"""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT coalesce(metadata_json->>'document_category', '未分类') AS cat,
                       count(*) AS n
                FROM documents
                WHERE project_id IS NULL
                GROUP BY 1
                """
            )
            rows = cursor.fetchall()
    counts = {str(row[0]): int(row[1]) for row in rows}
    counts["全部"] = sum(counts.values())
    return counts


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
            # Filter to insertable image docs IN SQL across the whole KB. The old
            # "LIMIT 200 most-recent then filter in Python" silently hid older
            # image evidence once the KB grew (e.g. 公司证件 imported before
            # thousands of 人员证件/业绩 docs fell outside the 200-row window).
            cursor.execute(
                """
                SELECT id, file_name, file_path, file_type, metadata_json
                FROM documents
                WHERE project_id IS NULL
                  AND lower(file_type) IN ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp')
                  AND coalesce(metadata_json->>'image_insertable', '') <> 'false'
                ORDER BY created_at DESC, id DESC
                LIMIT 5000
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


def list_performance_records(limit: int = 15) -> list[dict[str, str]]:
    """业绩台账记录(供资格响应附录列近年类似业绩)。解析入库的结构化业绩文本。"""
    import re as _re

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT content, metadata->>'project_year', metadata->>'project_type'
                FROM knowledge_chunks
                WHERE metadata->>'document_category' = '业绩'
                  AND content LIKE %s
                ORDER BY (metadata->>'project_year') DESC NULLS LAST, id DESC
                LIMIT %s
                """,
                ["业绩项目：%", max(1, limit)],
            )
            rows = cursor.fetchall()
    records: list[dict[str, str]] = []
    for content, year, project_type in rows:
        name = _re.search(r"业绩项目：([^\n]+)", content or "")
        amount = _re.search(r"中标金额：([^\n]+)", content or "")
        records.append(
            {
                "name": (name.group(1).strip() if name else ""),
                "amount": (amount.group(1).strip() if amount else ""),
                "year": str(year or ""),
                "type": str(project_type or ""),
            }
        )
    return records


def list_key_personnel(limit: int = 40) -> list[dict[str, str]]:
    """主要注册人员(建造师/职称等),按姓名去重(供资格响应附录列主要人员)。"""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT metadata->>'owner_name' AS owner,
                       string_agg(DISTINCT metadata->>'certificate_type', '、') AS certs
                FROM knowledge_chunks
                WHERE metadata->>'document_category' = '人员证件'
                  AND metadata->>'certificate_type' IN
                      ('一级建造师证', '二级建造师证', '注册安全工程师证',
                       '造价工程师证', '职称证书')
                  AND coalesce(metadata->>'owner_name', '') <> ''
                GROUP BY metadata->>'owner_name'
                ORDER BY owner
                LIMIT %s
                """,
                [max(1, limit)],
            )
            rows = cursor.fetchall()
    return [{"name": str(r[0]), "certs": str(r[1] or "")} for r in rows]


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
        conn.commit()

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
        conn.commit()

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


def list_project_materials(
    project_id: int, limit: int = 200
) -> list[dict[str, object]]:
    """List a project's own technical-material documents (M23).

    Project-scoped mirror of ``list_knowledge_documents``: filters on the real
    ``documents.project_id`` column so each project sees only its own uploaded
    施工组织设计 references — never the global library or another project's.
    """
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
                WHERE documents.project_id = %s
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
                [project_id, limit],
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


def list_project_insert_images(project_id: int) -> list[dict[str, object]]:
    """② 本项目用于插入文档的图片(航拍图/本项目图纸):image_insertable + 本项目范围。

    返回 ``[{document_id, file_name, target_section, caption}]``,供生成时按 target_section
    把图插到技术卷对应节(见 v2_generation_service._inject_project_images)。
    """
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, file_name, metadata_json
                FROM documents
                WHERE project_id = %s
                  AND coalesce(metadata_json->>'image_insertable', '') = 'true'
                ORDER BY created_at, id
                """,
                (project_id,),
            )
            rows = cursor.fetchall()
    images: list[dict[str, object]] = []
    for doc_id, file_name, metadata in rows:
        metadata = metadata or {}
        images.append(
            {
                "document_id": int(doc_id),
                "file_name": file_name,
                "target_section": metadata.get("target_section", ""),
                "caption": metadata.get("caption", "") or file_name,
            }
        )
    return images


def delete_project_material(project_id: int, document_id: int) -> None:
    """Delete one of a project's own materials (M23).

    Scoped to ``project_id`` so a project can never delete a global-library doc
    or another project's material.
    """
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM documents
                WHERE id = %s AND project_id = %s
                RETURNING file_path
                """,
                (document_id, project_id),
            )
            row = cursor.fetchone()
        conn.commit()

    if not row:
        raise ValueError(
            f"Project {project_id} material {document_id} was not found"
        )

    object_name = row[0]
    if object_name:
        try:
            minio_client.remove_file(settings.minio_bucket, str(object_name))
        except Exception:
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
