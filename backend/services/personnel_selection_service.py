"""项目经理选派:从招标资格条款解析项目经理要求 → 按名册推荐匹配候选。

要求解析走"派生"(扫已解析的 qualification_list/评分项文本),不改 parser 契约、对存量
项目即时可用。推荐按 建造师等级(高可顶低)+专业 打分排序,安全B证作加分(用户定:先不
硬卡B证)。
"""

from __future__ import annotations

from typing import Any

from schemas.personnel import (
    PersonnelMember,
    PMRecommendation,
    PMRequirement,
)

# 建造师等级高低:一级可顶二级要求。
_LEVEL_RANK = {"二级建造师": 1, "一级建造师": 2}
_SPECIALTY_KEYWORDS = (
    "公路工程", "市政公用工程", "市政公用", "建筑工程", "机电工程",
    "水利水电", "铁路工程", "港口与航道", "通信与广电", "矿业工程", "民航机场",
)


def _level_rank(level: str) -> int:
    for key, rank in _LEVEL_RANK.items():
        if key in (level or ""):
            return rank
    return 0


def derive_pm_requirement(requirements: Any) -> PMRequirement:
    """从招标要求里派生项目经理硬性要求。

    扫 ``qualification_list`` 与技术评分项里提到"项目经理/建造师"的条目,关键词抽
    等级(一/二级)、专业、安全B证。抽不到的留空(=不限),让推荐尽量宽而不漏。
    """
    items = list(getattr(requirements, "qualification_list", []) or [])
    items += list(getattr(requirements, "technical_score_items", []) or [])
    texts = [
        f"{getattr(it, 'title', '')} {getattr(it, 'description', '')}"
        for it in items
    ]
    pm_text = " ".join(
        t for t in texts if ("项目经理" in t or "建造师" in t or "项目负责人" in t)
    )

    level = ""
    if "一级建造师" in pm_text or "一级注册建造师" in pm_text:
        level = "一级建造师"
    elif "二级建造师" in pm_text or "二级注册建造师" in pm_text:
        level = "二级建造师"

    specialty = ""
    for keyword in _SPECIALTY_KEYWORDS:
        if keyword in pm_text:
            specialty = "市政公用工程" if keyword == "市政公用" else keyword
            break

    requires_b = (
        "安全生产考核" in pm_text or "安全考核" in pm_text or "B证" in pm_text
    ) and ("B" in pm_text or "b" in pm_text or "项目负责人" in pm_text)

    return PMRequirement(
        builder_level=level,
        builder_specialty=specialty,
        requires_safety_b=requires_b,
        note=pm_text[:160],
    )


def _score_member(
    member: PersonnelMember, requirement: PMRequirement
) -> PMRecommendation | None:
    """给一个候选打分;不满足硬性等级时返回 None(不进推荐)。"""
    if not member.is_pm_candidate:
        return None

    matched: list[str] = []
    gaps: list[str] = []
    score = 0.0

    # 等级:候选最高等级 ≥ 要求等级 即达标(一级可顶二级)。
    req_rank = _level_rank(requirement.builder_level)
    cand_rank = max((_level_rank(level) for level in member.builder_levels), default=0)
    if req_rank:
        if cand_rank >= req_rank:
            score += 2.0
            matched.append(f"等级达标:{'/'.join(member.builder_levels)}")
        else:
            return None  # 等级不够,硬性不满足
    elif cand_rank:
        score += 1.0  # 不限等级时,有证即可,高等级略加分
        score += 0.1 * cand_rank

    # 专业:要求专业在候选建造师专业里 → 匹配;候选"未注明专业"→ 待核验(不淘汰)。
    if requirement.builder_specialty:
        if requirement.builder_specialty in member.builder_specialties:
            score += 2.0
            matched.append(f"专业匹配:{requirement.builder_specialty}")
        elif not member.builder_specialties:
            score += 0.3
            gaps.append("专业待核验(名册未注明)")
        else:
            gaps.append(
                f"专业不符(本人:{'/'.join(member.builder_specialties)})"
            )
    elif member.builder_specialties:
        matched.append(f"专业:{'/'.join(member.builder_specialties)}")

    # 安全B证:用户定不硬卡,有则加分,无则记缺口。
    if "B" in member.safety_cert_classes:
        score += 1.0
        matched.append("持安全B证")
    elif requirement.requires_safety_b:
        gaps.append("缺安全B证(招标要求,需人工补)")

    # 在职/数据可信度:台账来源优先于知识库(后者可能离职/过期)。
    if member.source == "台账":
        score += 0.5
    elif member.source == "知识库":
        gaps.append("名册来源=知识库,需核验在职/有效期")

    return PMRecommendation(member=member, score=round(score, 2), matched=matched, gaps=gaps)


def recommend_project_managers(
    roster: list[PersonnelMember], requirement: PMRequirement, limit: int = 20
) -> list[PMRecommendation]:
    """按要求从名册推荐项目经理候选,分高在前。"""
    scored = [
        rec
        for rec in (_score_member(member, requirement) for member in roster)
        if rec is not None
    ]
    scored.sort(key=lambda rec: (-rec.score, rec.member.name))
    return scored[:limit]
