"""逐空核对引擎:投标规格 + 我方资料 → 每个空"找要求→核对→填/告警"→ 核对报告。

纯逻辑、不依赖 LLM(规格由 tender_spec_service 用 LLM 抽好后传入),便于测试。
本切片覆盖 4 个有代表性的空:工期(填from出处)、企业资质(达标核对)、项目经理(达标核对)、
投标人基本情况表附件(缺证/缺料核对)。每加一个空 = 往这里加一条规则,不改架构。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from schemas.tender_spec import (
    ConformanceReport,
    FillRequirement,
    TenderSpec,
)

# 资质等级高低(特级 > 一级 > 二级 > 三级);壹/贰/叁 归一到 一/二/三。
_GRADE_RANK = {"特级": 4, "一级": 3, "二级": 2, "三级": 1}
_GRADE_NORMALIZE = {"壹级": "一级", "贰级": "二级", "叁级": "三级"}
_DEFAULT_BASIC_INFO_ATTACHMENTS = ["营业执照", "资质证书", "安全生产许可证"]

# 证件"即将到期"窗口:到期前 90 天内就预警(投标+工期跨度内别失效)。
_EXPIRY_SOON_DAYS = 90
# 从有效期文本里抠日期:支持 2028 / 2028-05 / 2028.5.15 / 2028年5月15日 等。
_DATE_RE = re.compile(r"(20\d{2})[.\-_/年]?(1[0-2]|0?[1-9])?[.\-_/月]?(3[01]|[12]\d|0?[1-9])?")


def _parse_valid_to(raw: str) -> str:
    """有效期文本 → ISO 日期(YYYY-MM-DD)。

    取"至"之后那段(如 "2023至2028" → 2028);只有年→当年末(12-31);只有年月→该月 28
    (保守、避开月末长度坑)。抠不出返回 ""。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if "至" in text:
        text = text.rsplit("至", 1)[-1].strip()
    match = _DATE_RE.search(text)
    if not match:
        return ""
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else 12
    if match.group(3):
        day = int(match.group(3))
    elif match.group(2):
        day = 28
    else:
        day = 31
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return date(year, month, 28).isoformat()


def _expiry_status(valid_to_iso: str, today: date) -> tuple[str, int]:
    """ISO 有效期 + 今天 → (状态, 剩余天数)。状态:已过期/即将到期/有效/未知。"""
    if not valid_to_iso:
        return ("未知", 0)
    try:
        expires = date.fromisoformat(valid_to_iso)
    except ValueError:
        return ("未知", 0)
    days = (expires - today).days
    if days < 0:
        return ("已过期", days)
    if days <= _EXPIRY_SOON_DAYS:
        return ("即将到期", days)
    return ("有效", days)


def _normalize_grades(text: str) -> str:
    for raw, norm in _GRADE_NORMALIZE.items():
        text = text.replace(raw, norm)
    return text


def _grade_rank(text: str) -> int:
    text = _normalize_grades(text or "")
    for grade, rank in _GRADE_RANK.items():
        if grade in text:
            return rank
    return 0


def _strip_grade(text: str) -> str:
    text = _normalize_grades(text or "")
    for grade in _GRADE_RANK:
        text = text.replace(grade, "")
    return text.replace("及以上", "").strip()


def check_qualification(
    spec: TenderSpec, profile: dict[str, Any]
) -> FillRequirement | None:
    """企业资质达标核对:招标要求的资质 vs 公司档案资质等级。

    要求里抽出专业+等级;公司资质按 ；/;/、 拆成多项,只要有一项"同专业且等级≥要求"
    即达标。不达标 = 废标级,标 status=不符合、action=告警(绝不填个低级蒙混)。
    """
    cert = next(
        (
            c
            for c in spec.cert_requirements
            if "资质" in c.cert_type and _grade_rank(c.required_value)
        ),
        None,
    )
    if cert is None:
        return None  # 招标没明确企业资质等级要求 → 本切片不核

    # 招标要求常是整句("具有有效的公路工程施工总承包叁级及以上资质…"),含多个等级词。
    # 取最低要求等级(_grade_rank 命中最具体/最低那个,如"三级及以上"→三级)。
    req_rank = _grade_rank(cert.required_value)
    required_norm = _normalize_grades(cert.required_value)
    ours = _normalize_grades(str(profile.get("qualification_grade", "") or ""))
    our_items = [seg.strip() for seg in _split_quals(ours) if seg.strip()]

    matched_best = ""
    meets = False
    for item in our_items:
        our_specialty = _strip_grade(item)  # 如 "公路工程施工总承包"
        # 方向修正:看**我方这个专业是否被招标要求提及**(整句里含我方专业)。
        mentioned = our_specialty and (
            our_specialty in required_norm
            or (len(our_specialty) >= 4 and our_specialty[:4] in required_norm)
        )
        if mentioned:
            matched_best = matched_best or item
            if _grade_rank(item) >= req_rank:
                meets = True
                matched_best = item
                break

    return FillRequirement(
        field="企业资质",
        source=cert.source or "资格审查条件",
        required=cert.required_value,
        our_value=matched_best or (our_items[0] if our_items else "（档案无资质）"),
        status="符合" if meets else "不符合",
        action="填" if meets else "告警",
        note="" if meets else "本公司同专业资质等级不达标,本项目可能没资格投——务必人工复核",
    )


def _split_quals(text: str) -> list[str]:
    import re

    return re.split(r"[；;、,，\n]", text or "")


def check_project_manager(
    requirement: Any, selected_pm: dict[str, Any] | None
) -> FillRequirement:
    """项目经理达标核对:招标要求(建造师等级+专业)vs 本项目选派的人。

    requirement 是 personnel_selection_service.derive_pm_requirement 的产物。
    没选派 → 待人工;选了但等级/专业不符 → 不符合告警。
    """
    req_level = getattr(requirement, "builder_level", "") or ""
    req_specialty = getattr(requirement, "builder_specialty", "") or ""
    required = "/".join(p for p in (req_level, req_specialty) if p) or "（招标未明确）"

    if not selected_pm or not selected_pm.get("name"):
        return FillRequirement(
            field="项目经理",
            source="投标人须知（3.5.5）",
            required=required,
            our_value="（未选派）",
            status="待人工",
            action="告警",
            note="还没在「项目经理选派」里选人",
        )

    certs = selected_pm.get("builder_certs") or []
    levels = {c.get("level", "") for c in certs}
    specialties = {c.get("specialty", "") for c in certs}
    level_ok = (not req_level) or any(
        _grade_rank(level) >= _grade_rank(req_level) for level in levels
    )
    spec_ok = (not req_specialty) or (req_specialty in specialties)
    meets = level_ok and spec_ok
    gaps = []
    if not level_ok:
        gaps.append("建造师等级不够")
    if not spec_ok:
        gaps.append("专业不符")

    cert_desc = "/".join(
        f"{c.get('level', '')}{c.get('specialty', '')}" for c in certs
    )
    return FillRequirement(
        field="项目经理",
        source="投标人须知（3.5.5）",
        required=required,
        our_value=f"{selected_pm['name']}（{cert_desc}）",
        status="符合" if meets else "不符合",
        action="填" if meets else "告警",
        note="" if meets else "、".join(gaps),
    )


def check_pm_cert_expiry(
    selected_pm: dict[str, Any] | None, today: date
) -> FillRequirement | None:
    """选派项目经理的建造师证有效期核对:过期=废标级,临近到期=预警。

    用名册已结构化的 BuilderCert.valid_to(从台账 xlsx 抠出),不需 OCR。未选派/无证 →
    返回 None(check_project_manager 已分别告警,不重复刷屏)。
    """
    if not selected_pm or not selected_pm.get("name"):
        return None
    certs = selected_pm.get("builder_certs") or []
    if not certs:
        return None

    name = selected_pm.get("name", "")
    expired: list[str] = []
    soon: list[str] = []
    known = 0
    for cert in certs:
        label = f"{cert.get('level', '')}{cert.get('specialty', '')}".strip() or "建造师证"
        valid_to = _parse_valid_to(str(cert.get("valid_to", "") or ""))
        status, days = _expiry_status(valid_to, today)
        if status == "未知":
            continue
        known += 1
        if status == "已过期":
            expired.append(f"{label}已过期({valid_to})")
        elif status == "即将到期":
            soon.append(f"{label}{days}天后到期({valid_to})")

    cert_desc = "、".join(
        f"{(c.get('level', '') + c.get('specialty', '')).strip() or '建造师证'}"
        f"{('有效期至' + _parse_valid_to(str(c.get('valid_to', '') or ''))) if _parse_valid_to(str(c.get('valid_to', '') or '')) else '(无有效期信息)'}"
        for c in certs
    )
    base = dict(
        field="项目经理证件有效期",
        source="投标人须知（资格审查）",
        required="投标截止日仍在有效期内",
        our_value=f"{name}:{cert_desc}",
    )
    if expired:
        return FillRequirement(
            **base,
            status="不符合",
            action="告警",
            note="；".join(expired) + " —— 过期证件投标即废标,务必换证或换人",
        )
    if soon:
        return FillRequirement(
            **base,
            status="缺料",
            action="告警",
            note="；".join(soon) + " —— 临近到期,确认投标及工期内不失效",
        )
    if known == 0:
        return FillRequirement(
            **base,
            status="待人工",
            action="告警",
            note="选派项目经理的建造师证无有效期信息,人工核扫描件是否在有效期内",
        )
    return FillRequirement(
        **base,
        status="符合",
        action="留空",
        note="选派项目经理证件均在有效期内",
    )


def check_duration(spec: TenderSpec) -> FillRequirement | None:
    """工期:招标在前附表里规定了工期 → 投标函按它填(填from出处,不是核对我方)。"""
    if not spec.duration:
        return None
    return FillRequirement(
        field="工期",
        source="投标人须知前附表（1.3.2）",
        required=spec.duration,
        our_value=spec.duration,
        status="一致",
        action="填",
        note="投标函/投标函附录的工期均按此填,三处须一致",
    )


def check_basic_info_attachments(
    spec: TenderSpec, available_cert_types: set[str]
) -> FillRequirement:
    """投标人基本情况表后该附什么 + 我方有没有(缺证核对)。"""
    required = spec.attachment_requirements.get(
        "投标人基本情况表"
    ) or _DEFAULT_BASIC_INFO_ATTACHMENTS
    missing = [
        need
        for need in required
        if not any(need[:2] in have or have[:2] in need for have in available_cert_types)
    ]
    if missing:
        return FillRequirement(
            field="投标人基本情况表附件",
            source="投标人须知（3.5.1）",
            required="、".join(required),
            our_value="、".join(sorted(available_cert_types)) or "（证件库为空）",
            status="缺料",
            action="告警",
            note=f"缺:{'、'.join(missing)}",
        )
    return FillRequirement(
        field="投标人基本情况表附件",
        source="投标人须知（3.5.1）",
        required="、".join(required),
        our_value="、".join(required),
        status="待人工",
        action="留空",
        note="证件库都有,出标后人工核扫描件是否最新/未过期",
    )


def build_conformance_report(
    project_id: int,
    spec: TenderSpec,
    profile: dict[str, Any],
    pm_requirement: Any = None,
    selected_pm: dict[str, Any] | None = None,
    available_cert_types: set[str] | None = None,
    today: date | None = None,
) -> ConformanceReport:
    """组装本切片的逐空核对报告。today 可注入(便于测试),默认今天。"""
    today = today or date.today()
    items: list[FillRequirement] = []
    for result in (
        check_duration(spec),
        check_qualification(spec, profile),
    ):
        if result is not None:
            items.append(result)
    if pm_requirement is not None:
        items.append(check_project_manager(pm_requirement, selected_pm))
    pm_expiry = check_pm_cert_expiry(selected_pm, today)
    if pm_expiry is not None:
        items.append(pm_expiry)
    items.append(
        check_basic_info_attachments(spec, available_cert_types or set())
    )
    return ConformanceReport(project_id=project_id, items=items)
