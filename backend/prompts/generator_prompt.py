from __future__ import annotations

import re
from typing import Any


CONTENT_WRITER_SYSTEM_PROMPT = (
    "你是施工组织设计主笔，熟悉工程投标文件写作。"
    "只输出本节点正文，不输出标题、JSON、自查表或元话语。"
    "不得编造金额、人名、证号、日期等事实。"
    "不要写「我们建议」「建议您」「建议采用」「推荐采用」等推测性语句，"
    "应使用确定性工程用语如「本工程采用」「施工方法为」「具体措施如下」。"
)

_PII_PATTERNS = (
    re.compile(r"\d{17}[\dXx]"),
    re.compile(r"1[3-9]\d{9}"),
)
_PII_MASK = "████"


def redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub(_PII_MASK, text)
    return text


def _format_requirement_items(items: list[dict[str, Any]] | None, limit: int = 12) -> str:
    """Render score/invalid-bid requirement items as a bullet list for the prompt."""
    lines: list[str] = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        desc = str(item.get("description", "") or "").strip()
        if title and desc:
            lines.append(f"- {title}：{desc}")
        elif title or desc:
            lines.append(f"- {title or desc}")
    return "\n".join(lines)


def build_node_fill_prompt(
    *,
    node_title: str,
    project_name: str,
    requirements: dict[str, Any],
    company_name: str,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    tender_text: str = "",
    score_items: list[dict[str, Any]] | None = None,
    invalid_items: list[dict[str, Any]] | None = None,
    section_guidance: str = "",
    target_chars: int = 0,
) -> list[dict[str, str]]:
    """Focused V2 prompt for filling one construction-plan prose node.

    ``score_items`` / ``invalid_items`` are the评分项/废标项 the parser extracted
    that are relevant to THIS node; injecting them lets the writer respond to what
    the评委 actually scores instead of producing generic prose.
    """
    tenderer = str(requirements.get("tenderer_name", "") or "")
    duration = str(requirements.get("planned_duration", "") or "")
    scope = str(
        requirements.get("tender_scope", "")
        or requirements.get("project_scope", "")
        or ""
    )
    location = str(requirements.get("project_location", "") or "")
    quality = str(requirements.get("quality_standard", "") or "")
    safety = str(requirements.get("safety_target", "") or "")

    snippets: list[str] = []
    for chunk in (knowledge_chunks or [])[:8]:
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content", "") or chunk.get("snippet", "")).strip()
        if not content:
            continue
        # 区分"公司同类施工方案"(参照写法/工艺/深度)与一般证据素材,提示 LLM 别照搬施组数据。
        meta = chunk.get("metadata") or {}
        label = (
            "【公司同类施工方案·仅参照写法/工艺/深度】"
            if meta.get("document_category") == "施工方案"
            else "【素材】"
        )
        snippets.append(f"{label}\n{redact_pii(content)[:700]}")

    score_block = _format_requirement_items(score_items)
    invalid_block = _format_requirement_items(invalid_items)

    guidance_block = ""
    if section_guidance:
        guidance_block = f"\n## 本节必须覆盖的工程要点\n{section_guidance}\n"
    length_rule = ""
    if target_chars:
        length_rule = (
            f"\n8. 本节篇幅不少于 {target_chars} 字，分层次（小标题/分条）充分展开，"
            f"按上面'必须覆盖的工程要点'逐项写实写细，不灌水、不重复。"
        )

    user_prompt = f"""## 任务
撰写施工组织设计节点"{node_title}"的正文内容。

## 项目背景
- 项目名称：{project_name}
- 招标人：{tenderer or '见招标文件'}
- 投标人：{company_name}
- 建设地点：{location or '见招标文件'}
- 工期：{duration or '见招标文件'}
- 质量目标：{quality or '见招标文件'}
- 安全目标：{safety or '见招标文件'}
- 招标范围：{scope or '见招标文件'}

## 知识库参考（含公司同类工程历史施工方案,供参照写法/工艺/深度,严禁照搬其数据）
{chr(10).join(snippets) if snippets else '（未匹配到相关知识片段）'}
{guidance_block}
## 本节点须正面响应的评分点
{score_block or '（本节点无直接对应评分点，按通用施工组织设计深度撰写）'}

## 本节点须规避的废标项
{invalid_block or '（无直接对应废标项）'}

## 写作风格与深度
- 紧扣本工程的项目名称、建设地点、规模与招标范围展开，避免可套用到任何项目的通用空话。
- 用确定性工程用语（"本工程采用""施工方法为""具体措施如下"），不写"我们建议""可考虑"等推测语。
- 给出可量化指标（数值、规格、频次、验收标准、责任分工），少用形容词、多用数据与步骤。
- 只撰写与本节点"{node_title}"直接相关的内容，不复述工程概况/项目背景，不与其他章节重复；
  上面的项目背景仅作为约束（确保工期、质量与安全目标、工程量等表述与全文一致），不得整段照搬或改写概况。

## 写作规则
1. 只写本节点正文，不得输出任何标题或 Markdown 标题符号。
2. 每节至少 8 段连贯论述，包含工程参数、操作步骤、验收标准和应急预案。
3. 列表型内容可用 Markdown 表格，表格应有实际字段和值；无依据的值留"________"。
4. 不写"人工确认点""待补充""TODO""AI生成"等元话语。
5. 不编造金额、人名、证号、日期；知识库只作素材，不得改变招标文件结构。
   标【公司同类施工方案】的片段:**只参照其写法、工艺步骤、措施条理与深度**,工程参数
   (项目名、地点、规模、工期、数据)一律以本项目招标为准,**严禁照搬历史项目的具体数值/
   地名/项目名**。
6. 逐条正面响应上述评分点，给出对应的、可量化的工程措施与验收标准，不要泛泛而谈。
7. 确保不触发上述废标项；涉及承诺事项用确定性表述明确承诺。{length_rule}

## 输出
直接输出本节点正文。"""

    return [
        {"role": "system", "content": CONTENT_WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
