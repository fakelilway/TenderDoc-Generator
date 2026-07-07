"""业绩选择:按招标"类似业绩"要求(近X年/金额≥Y/同类/N个)从台账推荐匹配,供多选。

与项目经理/总工选派同构,但业绩是**多选**(招标常要 N 个)。推荐源用 performance_archive_service
的台账(list_performance_ledger),并标注哪些业绩有证明扫描(有证据链的优先)。
"""

from __future__ import annotations

import re
from typing import Any

from schemas.tender_spec import PerformanceRequirement
from services import performance_archive_service as pa


def derive_performance_requirement(requirements: Any) -> PerformanceRequirement:
    """取招标已解析的类似业绩要求;没有则返回空要求(=不限,列全部供人工选)。"""
    pr = getattr(requirements, "performance_requirement", None)
    if isinstance(pr, PerformanceRequirement):
        return pr
    if isinstance(pr, dict):
        return PerformanceRequirement(**pr)
    return PerformanceRequirement()


def _amount_wan(text: str) -> float:
    """'326.86万元' → 326.86;'1.2亿' → 12000。"""
    s = str(text or "")
    m = re.search(r"([\d.]+)\s*亿", s)
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r"([\d.]+)", s)
    return float(m.group(1)) if m else 0.0


def _since_year(since: str) -> int:
    """'2022年以来' → 2022;'近3年' → 0(无绝对年,不卡)。"""
    m = re.search(r"(20\d{2})", str(since or ""))
    return int(m.group(1)) if m else 0


def _score(item: dict[str, Any], req: PerformanceRequirement, has_evidence: bool) -> dict[str, Any]:
    matched: list[str] = []
    gaps: list[str] = []
    score = 0.0

    year = int(str(item.get("year") or "0")[:4] or 0) if str(item.get("year") or "").strip() else 0
    amount = _amount_wan(item.get("amount", ""))
    itype = str(item.get("type") or "")

    # 时间
    since_y = _since_year(req.since)
    if since_y:
        if year and year >= since_y:
            score += 1.5
            matched.append(f"{year}年≥{since_y}")
        elif year:
            gaps.append(f"{year}年早于要求{since_y}")

    # 金额
    if req.min_amount_wan:
        if amount >= req.min_amount_wan:
            score += 2.0
            matched.append(f"金额{amount:.0f}万≥{req.min_amount_wan:.0f}万")
        else:
            gaps.append(f"金额{amount:.0f}万<{req.min_amount_wan:.0f}万")

    # 类型/同类
    if req.category:
        if req.category in itype or itype in req.category:
            score += 2.0
            matched.append(f"同类:{itype}")
        elif itype:
            gaps.append(f"类型{itype}≠{req.category}")

    # 有证明扫描的优先(资格审查要附中标/合同/交工)
    if has_evidence:
        score += 1.0
        matched.append("有证明扫描")
    else:
        gaps.append("缺证明扫描")

    return {
        "name": item.get("name", ""),
        "year": str(item.get("year") or ""),
        "amount": item.get("amount", ""),
        "type": itype,
        "manager": item.get("manager", ""),
        "document_id": item.get("document_id"),
        "has_evidence": has_evidence,
        "score": round(score, 2),
        "matched": matched,
        "gaps": gaps,
    }


def recommend_performance(
    requirement: PerformanceRequirement, limit: int = 40
) -> list[dict[str, Any]]:
    """按要求从台账推荐类似业绩,分高在前(有证明、同类、达标金额优先)。"""
    ledger = pa.list_performance_ledger()
    groups = pa.list_evidence_groups()
    evidence_norms = {pa._norm(name) for name in groups}

    scored = []
    for item in ledger:
        has_ev = pa._norm(str(item.get("name", ""))) in evidence_norms
        scored.append(_score(item, requirement, has_ev))
    scored.sort(key=lambda r: (-r["score"], str(r["name"])))
    return scored[:limit]


def _curated_as_item(record: dict[str, Any]) -> dict[str, Any]:
    """员工整理的信息表记录 → 打分/展示用的统一条目形状。"""
    amount_wan = record.get("amount_wan")
    return {
        "name": record.get("project_name") or "",
        "year": str(record.get("project_year") or ""),
        "amount": (
            f"{amount_wan}万元" if amount_wan is not None
            else str(record.get("contract_price") or "")
        ),
        "type": record.get("project_type") or "",
        "manager": record.get("project_manager") or "",
        "document_id": record.get("document_id"),
    }


def recommend_curated_performance(
    requirement: PerformanceRequirement,
) -> list[dict[str, Any]]:
    """投标人业绩候选池:员工整理的《类似项目信息表》全部记录,按招标要求打分排序。

    这些记录字段全(发包人三要素/合同价/监理/工期…),选中即可把"投标人近年完成的
    类似项目信息表"填满,故用它们而非台账当候选。与项目经理是谁无关。
    """
    from services import similar_project_info_service as spi

    records = spi.list_similar_project_records()
    evidence_norms = {pa._norm(name) for name in pa.list_evidence_groups()}
    scored = []
    for record in records:
        item = _curated_as_item(record)
        has_ev = pa._norm(item["name"]) in evidence_norms
        scored.append(_score(item, requirement, has_ev))
    scored.sort(key=lambda r: (-r["score"], str(r["name"])))
    return scored
