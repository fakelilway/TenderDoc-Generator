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
