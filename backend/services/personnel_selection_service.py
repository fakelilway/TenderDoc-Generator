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
    TechDirectorRequirement,
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
    member: PersonnelMember,
    requirement: PMRequirement,
    perf_count: int = 0,
) -> PMRecommendation | None:
    """给一个候选打分;不满足硬性等级时返回 None(不进推荐)。

    perf_count=此人在《类似项目信息表》里当项目经理的项目数。带过项目的人**保底入选**
    (公司真让他带过,是最硬的胜任证据):证件/等级不满足招标要求也列出来,但挂
    "废标风险,慎选"的明白警告,让用户自己权衡——系统不藏人,只把风险说清。
    """
    proven = perf_count > 0
    if not member.is_pm_candidate and not proven:
        return None

    matched: list[str] = []
    gaps: list[str] = []
    score = 0.0

    if not member.is_pm_candidate:
        gaps.append("名册无建造师证记录(凭业绩保底入选)——证件需人工核验")

    # 等级:候选最高等级 ≥ 要求等级 即达标(一级可顶二级)。
    req_rank = _level_rank(requirement.builder_level)
    cand_rank = max((_level_rank(level) for level in member.builder_levels), default=0)
    if req_rank:
        if cand_rank >= req_rank:
            score += 2.0
            matched.append(f"等级达标:{'/'.join(member.builder_levels)}")
        elif proven:
            gaps.append(
                f"建造师等级不满足招标要求({requirement.builder_level})——废标风险,慎选"
            )
        else:
            return None  # 等级不够且无业绩背书,硬性不满足
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

    # 业绩背书:信息表里真带过项目,按项目数加分(封顶1.5),真带过的人排前面
    if proven:
        score += min(1.5, 0.3 * perf_count)
        matched.append(f"业绩:当过{perf_count}个项目的项目经理")

    return PMRecommendation(member=member, score=round(score, 2), matched=matched, gaps=gaps)


def _norm_name(name: str) -> str:
    import re as _re

    return _re.sub(r"[\s　]+", "", name or "")


def recommend_project_managers(
    roster: list[PersonnelMember],
    requirement: PMRequirement,
    limit: int = 20,
    performance_counts: dict[str, int] | None = None,
) -> list[PMRecommendation]:
    """按要求从名册推荐项目经理候选,分高在前。

    performance_counts={归一化姓名:当经理的项目数}(来自《类似项目信息表》):
    带过项目的人保底入选+按项目数加分,且**不受前N名截断**(分不够也追加在尾部,不藏人)。"""
    counts = performance_counts or {}
    scored = [
        rec
        for rec in (
            _score_member(member, requirement, counts.get(_norm_name(member.name), 0))
            for member in roster
        )
        if rec is not None
    ]
    scored.sort(key=lambda rec: (-rec.score, rec.member.name))
    top = scored[:limit]
    top += [
        rec for rec in scored[limit:]
        if counts.get(_norm_name(rec.member.name), 0) > 0
    ]
    return top


# ── 项目技术负责人(总工)选派 ──────────────────────────────────────────────
# 总工看职称(高级>中级)+专业,与项目经理(建造师证)不同。
_TITLE_RANK = {"正高": 4, "高级": 3, "副高": 3, "中级": 2, "工程师": 2, "助理": 1, "初级": 1}


def _title_rank(title: str) -> int:
    t = title or ""
    # 先匹配高级(含"高级工程师"),再中级,避免"高级工程师"里的"工程师"误判中级
    if "正高" in t:
        return 4
    if "高级" in t or "副高" in t:
        return 3
    if "中级" in t:
        return 2
    if "助理" in t or "初级" in t:
        return 1
    if "工程师" in t:  # 裸"工程师"=中级
        return 2
    return 0


def derive_tech_director_requirement(requirements: Any) -> TechDirectorRequirement:
    """从招标里派生总工(项目技术负责人)硬性要求:职称等级 + 专业 + 是否要注册。"""
    items = list(getattr(requirements, "qualification_list", []) or [])
    items += list(getattr(requirements, "technical_score_items", []) or [])
    texts = [
        f"{getattr(it, 'title', '')} {getattr(it, 'description', '')}" for it in items
    ]
    tech_text = " ".join(
        t
        for t in texts
        if ("技术负责人" in t or "总工" in t or "项目总工" in t)
    )

    title_level = ""
    if "高级" in tech_text or "正高" in tech_text or "副高" in tech_text:
        title_level = "高级职称"
    elif "中级" in tech_text:
        title_level = "中级职称"

    specialty = ""
    for keyword in _SPECIALTY_KEYWORDS:
        if keyword in tech_text:
            specialty = "市政公用工程" if keyword == "市政公用" else keyword
            break

    requires_reg = "注册建造师" in tech_text or "注册" in tech_text

    return TechDirectorRequirement(
        title_level=title_level,
        specialty=specialty,
        requires_registration=requires_reg,
        note=tech_text[:160],
    )


def _score_tech(
    member: PersonnelMember,
    requirement: TechDirectorRequirement,
    perf_count: int = 0,
) -> PMRecommendation | None:
    """给一个总工候选打分;有职称即入选(职称是总工核心),硬等级不够则淘汰。

    perf_count=此人在《类似项目信息表》里当技术负责人的项目数。带过的人保底入选:
    职称不满足招标要求也列出来,挂"废标风险,慎选"警告(例:许明英职称工程师却当过
    15个项目的总工,招标要高级职称时她不该被藏起来,该由用户权衡)。
    """
    proven = perf_count > 0
    cand_rank = _title_rank(member.title)
    if cand_rank == 0 and not member.builder_certs and not proven:
        return None  # 无职称也无建造师也无业绩背书 → 不像总工候选

    matched: list[str] = []
    gaps: list[str] = []
    score = 0.0

    req_rank = _title_rank(requirement.title_level)
    if req_rank:
        if cand_rank >= req_rank:
            score += 2.0
            matched.append(f"职称达标:{member.title or '—'}")
        elif proven:
            gaps.append(
                f"职称不满足招标要求({requirement.title_level},"
                f"本人{member.title or '无职称'})——废标风险,慎选"
            )
        else:
            return None  # 职称不够且无业绩背书,硬性不满足
    elif cand_rank:
        score += 1.0 + 0.1 * cand_rank

    # 专业:看职称专业,其次建造师专业
    cand_specialties = [member.title_specialty, *member.builder_specialties]
    cand_specialties = [s for s in cand_specialties if s]
    if requirement.specialty:
        if any(requirement.specialty in s or s in requirement.specialty for s in cand_specialties):
            score += 2.0
            matched.append(f"专业匹配:{requirement.specialty}")
        elif not cand_specialties:
            score += 0.3
            gaps.append("专业待核验(名册未注明)")
        else:
            gaps.append(f"专业不符(本人:{'/'.join(cand_specialties)})")
    elif cand_specialties:
        matched.append(f"专业:{'/'.join(cand_specialties)}")

    # 要注册:有建造师证加分
    if requirement.requires_registration:
        if member.builder_certs:
            score += 1.0
            matched.append("持注册建造师证")
        else:
            gaps.append("缺注册建造师证(招标要求,需人工补)")

    if member.source == "台账":
        score += 0.5
    elif member.source == "知识库":
        gaps.append("名册来源=知识库,需核验在职/有效期")

    # 业绩背书:信息表里真当过技术负责人,按项目数加分(封顶1.5)
    if proven:
        score += min(1.5, 0.3 * perf_count)
        matched.append(f"业绩:当过{perf_count}个项目的技术负责人")

    return PMRecommendation(member=member, score=round(score, 2), matched=matched, gaps=gaps)


def recommend_tech_directors(
    roster: list[PersonnelMember],
    requirement: TechDirectorRequirement,
    limit: int = 20,
    performance_counts: dict[str, int] | None = None,
) -> list[PMRecommendation]:
    """按要求从名册推荐总工候选,分高在前。

    performance_counts={归一化姓名:当总工的项目数}:带过的人保底入选+按项目数加分,
    且不受前N名截断(分不够也追加在尾部,不藏人)。"""
    counts = performance_counts or {}
    scored = [
        rec
        for rec in (
            _score_tech(member, requirement, counts.get(_norm_name(member.name), 0))
            for member in roster
        )
        if rec is not None
    ]
    scored.sort(key=lambda rec: (-rec.score, rec.member.name))
    top = scored[:limit]
    top += [
        rec for rec in scored[limit:]
        if counts.get(_norm_name(rec.member.name), 0) > 0
    ]
    return top
