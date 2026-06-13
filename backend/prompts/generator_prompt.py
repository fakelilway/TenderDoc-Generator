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


def build_node_fill_prompt(
    *,
    node_title: str,
    project_name: str,
    requirements: dict[str, Any],
    company_name: str,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    previous_node_content: str = "",
    tender_text: str = "",
) -> list[dict[str, str]]:
    """Focused V2 prompt for filling one construction-plan prose node."""
    tenderer = str(requirements.get("tenderer_name", "") or "")
    duration = str(requirements.get("planned_duration", "") or "")
    scope = str(
        requirements.get("tender_scope", "")
        or requirements.get("project_scope", "")
        or ""
    )

    snippets: list[str] = []
    for chunk in (knowledge_chunks or [])[:5]:
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content", "") or chunk.get("snippet", "")).strip()
        if content:
            snippets.append(redact_pii(content)[:300])

    prev = ""
    if previous_node_content:
        prev = f"\n前一节内容（连贯性参考，不可重复）：\n{previous_node_content}"

    user_prompt = f"""## 任务
撰写施工组织设计节点"{node_title}"的正文内容。

## 项目背景
- 项目名称：{project_name}
- 招标人：{tenderer or '见招标文件'}
- 投标人：{company_name}
- 工期：{duration or '见招标文件'}
- 招标范围：{scope or '见招标文件'}

## 知识库参考
{chr(10).join(snippets) if snippets else '（未匹配到相关知识片段）'}

{prev}

## 写作规则
1. 只写本节点正文，不得输出任何标题或 Markdown 标题符号。
2. 每节至少 8 段连贯论述，包含工程参数、操作步骤、验收标准和应急预案。
3. 列表型内容可用 Markdown 表格，表格应有实际字段和值；无依据的值留"________"。
4. 不写"人工确认点""待补充""TODO""AI生成"等元话语。
5. 不编造金额、人名、证号、日期；知识库只作素材，不得改变招标文件结构。

## 输出
直接输出本节点正文。"""

    return [
        {"role": "system", "content": CONTENT_WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
