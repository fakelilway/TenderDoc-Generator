"""商务文件「通读整本招标 → 生成商务响应」的提示词。

产出四块(全部 Markdown,只用 ## / ### 标题与 | 管道表格,直接进商务卷渲染):
① 资格审查响应  ② 商务条款偏离表  ③ 声明与承诺  ④ 投标函关键值一致性提示
"""

from __future__ import annotations

from typing import Any


COMMERCIAL_RESPONSE_SYSTEM_PROMPT = (
    "你是投标商务文件编制专家，精通招标文件研读与商务条款逐条响应。"
    "你会通读整本招标文件，据此编制贴合本项目的商务响应，而非套用通用模板。"
    "只输出 Markdown 正文（## / ### 标题与 | 管道表格），不输出前言、结语或解释。"
    "不得编造金额、报价、证号、日期或企业身份；不确定一律写 ________ 或“待人工确认”。"
    "事实只能引用给定的“我方档案”，档案缺失的不得臆造。"
)


def _items_block(items: Any, limit: int = 40) -> str:
    lines: list[str] = []
    for it in (items or [])[:limit]:
        if isinstance(it, dict):
            title = str(it.get("title", "") or "").strip()
            desc = str(it.get("description", "") or "").strip()
        else:
            title = str(getattr(it, "title", "") or "").strip()
            desc = str(getattr(it, "description", "") or "").strip()
        if title and desc:
            lines.append(f"- {title}：{desc}")
        elif title or desc:
            lines.append(f"- {title or desc}")
    return "\n".join(lines) or "（无）"


_PROFILE_LABELS = (
    ("company_name", "公司名称"),
    ("credit_code", "统一社会信用代码"),
    ("qualification_grade", "资质等级"),
    ("registered_capital", "注册资本"),
    ("legal_representative", "法定代表人"),
    ("company_type", "企业类型"),
    ("registered_address", "注册地址"),
    ("safety_license_no", "安全生产许可证号"),
    ("project_manager_name", "拟派项目经理"),
    ("project_manager_cert", "项目经理建造师证号"),
    ("business_scope", "经营范围"),
)


def _profile_block(profile: dict[str, str] | None) -> str:
    lines: list[str] = []
    for key, label in _PROFILE_LABELS:
        val = str((profile or {}).get(key, "") or "").strip()
        lines.append(f"- {label}：{val or '（档案未填，请勿编造）'}")
    return "\n".join(lines)


def build_commercial_response_prompt(
    *,
    requirements: dict[str, Any],
    tender_text: str,
    profile: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """构建「通读整本招标 → 四块商务响应」的 messages。"""
    r = requirements or {}
    meta = "\n".join(
        [
            f"- 项目名称：{r.get('project_name', '') or '见招标文件'}",
            f"- 招标人：{r.get('tenderer_name', '') or '见招标文件'}",
            f"- 建设地点：{r.get('project_location', '') or '见招标文件'}",
            f"- 工期：{r.get('planned_duration', '') or '见招标文件'}",
            f"- 质量目标：{r.get('quality_standard', '') or '见招标文件'}",
            f"- 安全目标：{r.get('safety_target', '') or '见招标文件'}",
            f"- 投标截止/有效期：{r.get('bid_deadline', '') or '见招标文件'}",
        ]
    )
    qual = _items_block(r.get("qualification_list"))
    score = _items_block(r.get("technical_score_items"))
    invalid = _items_block(r.get("invalid_bid_items"))

    user = f"""## 任务
通读下方【招标文件全文】，为本项目编制“商务响应”，覆盖以下四部分，逐条贴合本招标、可直接采用。

## 我方（投标人）档案——事实来源，只能用这里的信息，缺失的不要编造
{_profile_block(profile)}

## 招标关键信息（已解析，供快速定位；一切以全文为准）
{meta}

### 资格审查条件（逐条）
{qual}

### 评分项
{score}

### 废标项
{invalid}

## 招标文件全文
{tender_text}

## 产出要求——只输出以下四部分的 Markdown，全部用 ## / ### 标题与 | 管道表格
## 一、资格审查响应
逐条对照招标资格审查条件，做成表格：| 招标资格要求 | 我方情况（用上面“我方档案”的真实信息） | 是否满足 | 对应证据材料 |。证据列指明附件类别（营业执照／资质证书／安许证／业绩证明／人员证书等）。

## 二、商务条款偏离表
通读招标合同条款与投标人须知，逐条做成表格：| 条款 | 招标要求 | 我方响应 | 偏离情况 |。偏离情况只填“无偏离／正偏离／负偏离”。至少覆盖工期、付款方式与进度款、质量保证（质保金／缺陷责任期）、违约金、投标有效期、投标保证金。涉及金额／报价一律不要编造，写 ________ 待人工确认。

## 三、声明与承诺
通读招标，识别本项目明确要求或惯例需提供的声明／承诺（如中小企业声明、廉洁／廉政承诺、履约承诺、不串通投标承诺、信息真实性承诺等），逐项以 ### 子标题起草贴合本项目的正文。企业身份类（如中小企业）若“我方档案”未知，写明“□ 是 □ 否（待企业确认）”，不要替企业认定。

## 四、投标函关键值一致性提示
从招标中找出“投标函正文／投标函附录／投标人须知前附表／报价”之间必须完全一致的关键值（工期、投标有效期、报价口径等），做成表格：| 关键值 | 招标规定 | 须保持一致的位置 | 备注 |，并提示三处不一致属废标级。系统无法确定的值标“待人工确认”。

## 硬规则
1. 只输出上述四部分正文，无前言无结语。
2. 仅用 ## / ### 标题与 | 管道表格；禁止图片语法、HTML、代码块。
3. 不编造金额、报价、证号、日期、企业身份；不确定写 ________ 或“待人工确认”。
4. 事实只用“我方档案”里的信息，缺失字段不得臆造。
5. 内容要具体、贴合本招标、可直接采用，不写放之四海皆准的空话。"""

    return [
        {"role": "system", "content": COMMERCIAL_RESPONSE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
