"""V2-M3 Form Filler Agent — auto-fill company info into format skeleton fields.

Design principle: fill known fields from company profile, leave unknowns as ________.
No LLM — this is a deterministic data-binding layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class FilledField:
    """A field that was recognized and filled (or left blank)."""
    label: str        # e.g. "投标人", "法定代表人", "项目经理"
    raw_text: str     # e.g. "（盖单位章）"
    matched: bool     # True if filled from profile
    value: str        # filled value or "________"


@dataclass
class FillResult:
    """Result of filling one section/template."""
    title: str
    raw_template: str
    filled_template: str
    fields: list[FilledField]
    missing: list[str]  # labels that couldn't be filled


# ── Field pattern matching ──────────────────────────────────────────────

# patterns: (regex to find in template, label, profile_key)
FILLABLE_FIELDS: list[tuple[str, str, str]] = [
    # Tender-specific fields (filled from project context)
    (r'（招标人名称）', '招标人', '招标人'),
    (r'（项目名称）', '项目名称', '项目名称'),
    (r'招标项目名称[：:]\s*[_＿]{2,}', '招标项目名称', '项目名称'),
    (r'工程质量[：:]\s*[_＿]{2,}|质量[标要][准求][：:]\s*[_＿]{2,}', '质量标准', '质量'),
    (r'安全目标[：:]\s*[_＿]{2,}|安全[标要][准求][：:]\s*[_＿]{2,}', '安全目标', '安全'),
    (r'工期[：:]\s*[_＿]{2,}|计划工期[：:]\s*[_＿]{2,}', '工期', '工期'),

    # Company identity
    (r'投标人[：:]\s*[（(]盖单位章[）)]', '投标人', 'company_name'),
    (r'投标人[：:]\s*[_＿]{2,}|投标人[：:]\s*$', '投标人', 'company_name'),
    (r'投标人名称[：:]\s*[_＿]{2,}|投标人名称[：:]\s*$', '投标人名称', 'company_name'),
    (r'法定代表[人人][：:]\s*[_＿]{2,}|法定代表[人人][：:]\s*[（(]签字[）)]', '法定代表人', 'legal_rep'),
    (r'法定代表[人人][：:]\s*$', '法定代表人', 'legal_rep'),
    (r'法定代表人或其委托代理人[：:]\s*[_＿]{2,}|法定代表人或其委托代理人[：:]\s*[（(]签字[）)]', '委托代理人', 'legal_rep'),
    (r'委托代理人[：:]\s*[_＿]{2,}|委托代理人[：:]\s*[（(]签字[）)]', '委托代理人', ''),

    # Contact info
    (r'地\s*址[：:]\s*[_＿]{2,}|地\s*址[：:]\s*$', '地址', 'address'),
    (r'邮政编码[：:]\s*[_＿]{2,}|邮政编码[：:]\s*$', '邮政编码', 'postal_code'),
    (r'电\s*话[：:]\s*[_＿]{2,}|电\s*话[：:]\s*$', '电话', 'phone'),
    (r'传\s*真[：:]\s*[_＿]{2,}|传\s*真[：:]\s*$', '传真', 'fax'),
    (r'电子邮件[：:]\s*[_＿]{2,}|电子邮件[：:]\s*$', '电子邮件', 'email'),

    # Business registration
    (r'营业执照[号登記]?[：:]\s*[_＿]{2,}|营业执照[号登記]?[：:]\s*$', '营业执照号', 'business_license_no'),
    (r'注册资本[：:]\s*[_＿]{2,}|注册资本[：:]\s*$', '注册资本', 'registered_capital'),
    (r'成立日期[：:]\s*[_＿]{2,}|成立日期[：:]\s*$', '成立日期', 'established_date'),
    (r'基本账户开户银行[：:]\s*[_＿]{2,}', '基本账户开户银行', 'bank_name'),
    (r'基本账户银行账号[：:]\s*[_＿]{2,}', '基本账户银行账号', 'bank_account'),

    # Qualification
    (r'企业资质等级[：:]\s*[_＿]{2,}|企业资质等级[：:]\s*$', '企业资质等级', 'qualification_level'),
    (r'安全生产许可证[：:]\s*[_＿]{2,}', '安全生产许可证编号', 'safety_permit_no'),

    # Project manager
    (r'项目经理[：:]\s*[_＿]{2,}|项目经理[：:]\s*$', '项目经理', 'project_manager_name'),
    (r'建造师[任职执业资格]?[：:]\s*[_＿]{2,}',
     '项目经理建造师', 'project_manager_cert_no'),
    (r'安全生产考核合[格证][：:]\s*[_＿]{2,}',
     '项目经理安考证', 'project_manager_safety_cert_no'),

    # Generic: any field with ________ after colon
    (r'([^\n：:]*[：:])\s*[_＿]{3,}', None, None),
]


def fill_page_template(
    raw_template: str,
    profile: dict[str, str],
    page_title: str = "",
) -> FillResult:
    """Fill a format page template with company profile data.

    Scans for recognizable blank fields and replaces them with profile values.
    Returns the filled template, matched fields, and a missing-field list.
    """
    filled = raw_template
    fields: list[FilledField] = []
    missing: list[str] = []

    # 1. Exact field match: known patterns with profile keys
    for pattern, label, profile_key in FILLABLE_FIELDS:
        if profile_key is None:
            continue  # skip generic catch-all
        m = re.search(pattern, filled)
        if not m:
            continue

        value = profile.get(profile_key, "")
        if value:
            old = m.group(0)
            # Handle parenthesized placeholders like （招标人名称）
            if '（' in old or '(' in old:
                new_text = old.replace(m.group(1) if m.lastindex else old, value)
            else:
                blank_pos = max(old.rfind('_'), old.rfind('＿'))
                if blank_pos < 0:
                    blank_pos = len(old)
                prefix = old[:blank_pos]
                new_text = f"{prefix}：{value}" if '：' not in prefix and ':' not in prefix[-3:] else f"{prefix} {value}"
            filled = filled.replace(old, new_text, 1)
            fields.append(FilledField(label=label, raw_text=old[:60], matched=True, value=value))
        else:
            fields.append(FilledField(label=label, raw_text="________", matched=False, value="________"))
            missing.append(label)

    # 2. Generic ________ pattern match
    if "________" in filled or "＿＿＿＿" in filled:
        # Any remaining blanks we don't recognize — mark as unknown
        remaining = len(re.findall(r'[_＿]{3,}', filled))
        if remaining > 0:
            fields.append(FilledField(
                label=f"未识别空白字段×{remaining}",
                raw_text=f"{remaining}处空白",
                matched=False,
                value="________"
            ))

    return FillResult(
        title=page_title,
        raw_template=raw_template,
        filled_template=filled,
        fields=fields,
        missing=missing,
    )


def generate_missing_checklist(results: list[FillResult]) -> list[str]:
    """Generate a human-readable missing-materials checklist."""
    all_missing: list[str] = []
    for r in results:
        if r.missing:
            all_missing.extend(f"【{r.title}】缺失: {', '.join(r.missing)}")

    if not all_missing:
        return ["所有已知字段已填写完毕。"]

    return all_missing
