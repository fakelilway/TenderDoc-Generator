from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from rag.retriever import RetrievalResult
from schemas.evidence import EvidenceItem, EvidencePack
from schemas.tender import TenderRequirements


COMPANY_CERT_KEYWORDS = (
    "营业执照",
    "资质证书",
    "安全生产许可证",
    "开户许可证",
    "基本存款账户",
    "企业资质",
    "公司证件",
)
PERSON_CERT_KEYWORDS = (
    "建造师",
    "身份证",
    "毕业证",
    "建安",
    "交安",
    "职称",
    "社保",
    "人员证件",
    "项目经理",
    "技术负责人",
    "安全员",
)
PERFORMANCE_KEYWORDS = ("业绩", "中标通知书", "合同", "验收", "交工", "竣工")
PRICING_KEYWORDS = ("报价", "工程量清单", "综合单价", "投标总价", "计价", "清单")
TABLE_KEYWORDS = ("附表", "表格", "计划表", "汇总表", "清单", "xlsx", "xls")
TECHNICAL_KEYWORDS = (
    "施工组织",
    "施工方案",
    "技术措施",
    "质量",
    "安全",
    "工期",
    "进度",
    "环保",
    "文明施工",
    "应急预案",
    "保通",
)
IMAGE_FILE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}


def build_evidence_pack(
    requirements: TenderRequirements,
    *,
    selected_references: list[dict[str, Any]] | None = None,
    image_references: list[dict[str, Any]] | None = None,
    retrieved_results: (
        Mapping[str, list[RetrievalResult | str]]
        | Iterable[RetrievalResult | str]
        | None
    ) = None,
) -> EvidencePack:
    pack = EvidencePack()
    seen_text_keys: set[tuple[int | None, int | None, str]] = set()
    seen_images: set[int] = set()

    for reference in selected_references or []:
        item = _item_from_reference(reference)
        if item.chunk_id is not None:
            pack.selected_chunk_ids.append(item.chunk_id)
        _add_text_item(pack, item, seen_text_keys)

    for result in _iter_results(retrieved_results):
        item = _item_from_result(result)
        if item:
            _add_text_item(pack, item, seen_text_keys)

    for reference in image_references or []:
        item = _item_from_image(reference)
        if item.document_id is None or item.document_id in seen_images:
            continue
        pack.image_evidence.append(item)
        seen_images.add(item.document_id)

    pack.selected_chunk_ids = sorted(set(pack.selected_chunk_ids))
    if not pack.all_items():
        pack.notes.append("未匹配到知识库资料，生成器将仅依据招标解析结果和人工确认目录生成。")
    elif not pack.technical_schemes:
        pack.notes.append("未匹配到可作为正文素材的技术方案类资料，证件资料不会直接进入技术正文。")
    if requirements.project_name:
        pack.notes.append(f"证据包已按项目“{requirements.project_name}”构建。")
    return pack


def _add_text_item(
    pack: EvidencePack,
    item: EvidenceItem,
    seen: set[tuple[int | None, int | None, str]],
) -> None:
    key = (item.chunk_id, item.document_id, item.content[:80])
    if key in seen:
        return
    seen.add(key)
    bucket = _classify_text_item(item)
    getattr(pack, bucket).append(item)


def _classify_text_item(item: EvidenceItem) -> str:
    text = item.search_text()
    if _contains_any(text, COMPANY_CERT_KEYWORDS) or item.owner_type == "公司":
        return "company_certificates"
    if _contains_any(text, PERSON_CERT_KEYWORDS) or item.owner_type == "人员":
        return "person_certificates"
    if _contains_any(text, PERFORMANCE_KEYWORDS):
        return "performance_projects"
    if _contains_any(text, PRICING_KEYWORDS):
        return "pricing_attachments"
    if _contains_any(text, TABLE_KEYWORDS):
        return "table_attachments"
    if _is_structured_evidence(item):
        return "other_references"
    if _contains_any(text, TECHNICAL_KEYWORDS):
        return "technical_schemes"
    return "other_references"


def _item_from_reference(reference: dict[str, Any]) -> EvidenceItem:
    metadata = dict(reference.get("metadata") or {})
    title = str(
        reference.get("title")
        or metadata.get("file_name")
        or metadata.get("source_path")
        or ""
    )
    return EvidenceItem(
        chunk_id=_int_or_none(reference.get("chunk_id")),
        document_id=_int_or_none(reference.get("document_id")),
        title=title,
        content=str(reference.get("content") or ""),
        metadata=metadata,
        evidence_type=_evidence_type(metadata),
        document_category=_optional_text(metadata.get("document_category")),
        certificate_type=_optional_text(metadata.get("certificate_type")),
        owner_type=_optional_text(metadata.get("owner_type")),
        owner_name=_optional_text(metadata.get("owner_name")),
        score=_float_or_none(reference.get("score")),
    )


def _item_from_result(result: RetrievalResult | str) -> EvidenceItem | None:
    if isinstance(result, str):
        content = result.strip()
        if not content:
            return None
        return EvidenceItem(content=content, evidence_type="retrieved_text")
    metadata = dict(result.metadata or {})
    title = str(metadata.get("file_name") or metadata.get("source_path") or "")
    return EvidenceItem(
        chunk_id=_int_or_none(result.chunk_id),
        document_id=_int_or_none(result.document_id),
        title=title,
        content=result.content,
        metadata=metadata,
        evidence_type=_evidence_type(metadata),
        document_category=_optional_text(metadata.get("document_category")),
        certificate_type=_optional_text(metadata.get("certificate_type")),
        owner_type=_optional_text(metadata.get("owner_type")),
        owner_name=_optional_text(metadata.get("owner_name")),
        score=_float_or_none(result.score),
    )


def _item_from_image(reference: dict[str, Any]) -> EvidenceItem:
    metadata = {
        key: value
        for key, value in reference.items()
        if key
        not in {
            "document_id",
            "file_name",
            "caption",
            "match_score",
        }
    }
    title = str(reference.get("caption") or reference.get("file_name") or "")
    return EvidenceItem(
        document_id=_int_or_none(reference.get("document_id")),
        title=title,
        metadata=metadata,
        evidence_type="image",
        document_category=_optional_text(reference.get("document_category")),
        certificate_type=_optional_text(reference.get("certificate_type")),
        owner_type=_optional_text(reference.get("owner_type")),
        owner_name=_optional_text(reference.get("owner_name")),
        score=_float_or_none(reference.get("match_score")),
    )


def _evidence_type(metadata: dict[str, Any]) -> str:
    file_type = str(metadata.get("file_type") or "").lower()
    if file_type in IMAGE_FILE_TYPES or metadata.get("image_insertable") is True:
        return "image_summary"
    if metadata.get("ingestion_mode") in {"structured_evidence", "evidence_only"}:
        return "structured_evidence"
    return "retrieved_text"


def _is_structured_evidence(item: EvidenceItem) -> bool:
    metadata = item.metadata or {}
    return (
        item.evidence_type in {"structured_evidence", "image_summary", "image"}
        or item.content.startswith("资料名称：")
        or metadata.get("ingestion_mode") in {"structured_evidence", "evidence_only"}
        or metadata.get("indexing_status") in {"structured_evidence", "evidence_only"}
    )


def _iter_results(
    retrieved_results: (
        Mapping[str, list[RetrievalResult | str]]
        | Iterable[RetrievalResult | str]
        | None
    ),
) -> Iterable[RetrievalResult | str]:
    if retrieved_results is None:
        return []
    if isinstance(retrieved_results, Mapping):
        flattened: list[RetrievalResult | str] = []
        for items in retrieved_results.values():
            flattened.extend(items or [])
        return flattened
    return retrieved_results


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    compact = re.sub(r"\s+", "", text)
    return any(keyword in compact for keyword in keywords)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
