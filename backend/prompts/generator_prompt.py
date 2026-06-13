from __future__ import annotations

import re
from typing import Any

from schemas.tender import TenderRequirements


GENERATOR_WRITER_SYSTEM_PROMPT = """你是投标文件主笔——有工程与商务合规经验，对格式节点树的绝对忠诚高于一切。只输出 Markdown 正文。不输出 JSON、元话语、自查表、页码、页眉页脚。不编造事实数据。"""

GENERATION_AUDITOR_SYSTEM_PROMPT = """你是投标文件结构/内容审查员。只输出合法 JSON，不输出 Markdown、不写正文、不合稿。"""


# Sample personal data leaked from historical bid documents must never reach
# the prompt: citizen ID numbers (18 digits, optional trailing X) and mainland
# mobile numbers are masked before any chunk is embedded.
_PII_PATTERNS = (
    re.compile(r"\d{17}[\dXx]"),  # 18-digit citizen ID, incl. trailing X
    re.compile(r"1[3-9]\d{9}"),  # 11-digit mobile number
)
_PII_MASK = "████"


def redact_pii(text: str) -> str:
    """Mask citizen IDs and mobile numbers in retrieved knowledge chunks."""
    for pattern in _PII_PATTERNS:
        text = pattern.sub(_PII_MASK, text)
    return text


def _clean_chunk(text: str) -> str:
    """Strip leaked page footers / dot leaders / noise from a retrieved chunk."""
    page_footer = re.compile(r"第\s*\d+\s*页\s*[/／共]?\s*\d*\s*页?")
    dots_only = re.compile(r"^[.·•。…\-—_=\s]+$")
    lines: list[str] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if page_footer.fullmatch(stripped) or dots_only.match(stripped):
            continue
        lines.append(page_footer.sub("", stripped))
    return "\n".join(lines).strip()






def build_volume_agent_prompt(
    *,
    volume: str,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    volume_skeleton: str = "",
    bid_plan: dict[str, Any] | None = None,
    template_name: str = "",
    pricing_strategy: dict[str, Any] | None = None,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    knowledge_images: list[dict[str, Any]] | None = None,
    tender_text: str = "",
    company_profile_block: str = "",
) -> list[dict[str, str]]:
    label = _volume_label(volume)
    node_tree = _format_volume_node_tree(requirements, volume)
    chunks = _format_long_context_chunks(
        _filter_chunks_for_volume(knowledge_chunks or [], volume)
    )
    images = _format_knowledge_images(knowledge_images)
    profile_section = (
        "\n### 企业档案（已人工核实）\n" f"{company_profile_block}\n"
        if company_profile_block
        else ""
    )

    skeleton_block = (
        volume_skeleton.strip()
        or f"# {requirements.project_name or '投标项目'} {label}\n\n{node_tree}"
    )

    user_prompt = f"""## 任务
在【本卷确定性骨架】内填充{label}卷正文。

## 本卷确定性骨架（来自招标文件投标文件格式，必须逐字保留）
{skeleton_block}

## 节点清单（用于核对标题、顺序和层级）
{node_tree}

## 规则（优先级从高到低）

### 规则1：节点不可变
【本卷确定性骨架】是唯一允许的结构。必须逐字保留所有标题、顺序和层级；不得新增、删除、合并或重命名任何标题。"其他内容""其他材料"等只有标题的兜底节点也必须保留标题占位，哪怕只有一行。如果骨架和下面任何规则或信息冲突，以骨架为准。违反此规则会被 Pass 1 审计打回重写。

### 规则2：表单照抄
投标函、法定代表人证明、授权委托书、保证金凭证、承诺书、资格审查表格、各类声明→优先使用【本卷确定性骨架】中已经抽取出的招标文件原文模板；骨架缺原文时再从下面【招标文件关键内容】找模板原文，逐字照抄。表格原样复制表头和列项，不改顺序不增删列。只替换公司名（→{company_name}）、法人代表、日期等已提供字段。无依据的留"________"。禁止改写。

### 规则3：方案自由写
施工组织设计、技术方案、施工部署→工程化连贯论述，每节≥2段。吸收工期/质量/安全信息。不写评分点摘要。正文用 Markdown 表格表达进度计划/人员配置/机械配置等列表型内容。

### 规则4：不知道的留空
金额、人名、证号、日期无依据→"________"或"详见已标价工程量清单"。不编造。不写"人工确认点""待补充""TODO""AI生成"等元话语。不输出知识库页码、目录点线、页眉页脚。

## 你应该知道的信息

### 项目核心字段
- 招标人：{requirements.tenderer_name or "________"}
- 建设地点：{requirements.project_location or "________"}
- 招标范围：{requirements.tender_scope or "________"}
- 计划工期：{requirements.planned_duration or "________"}
- 质量标准：{requirements.quality_standard or "________"}
- 安全目标：{requirements.safety_target or "________"}
- 投标截止时间：{requirements.bid_deadline or "________"}

### 招标文件格式要求
{requirements.bid_format_requirements or "- 招标文件未提取到明确格式要求；按节点树生成。"}
{profile_section}
### 招标文件关键内容
{_format_tender_text(tender_text)}

### 分卷任务边界
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

### 可用企业资料
{chunks or "暂无文本资料。请按招标文件要求和企业常规投标文件深度生成，不得编造企业事实。"}

{images}

## 输出
直接输出填充后的完整{label}卷 Markdown。第一行必须与【本卷确定性骨架】第一行一致。必须在骨架的每个标题节点下填充内容，不得删除、跳过、合并任何骨架节点。"其他内容""其他材料"等兜底节点必须保留标题，至少写一行说明。不得输出解释、JSON、自查表、元话语。
"""
    return [
        {"role": "system", "content": GENERATOR_WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_volume_revision_prompt(
    *,
    volume: str,
    draft_markdown: str,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    volume_skeleton: str = "",
    audit_feedback: str = "",
    bid_plan: dict[str, Any] | None = None,
    pricing_strategy: dict[str, Any] | None = None,
    tender_text: str = "",
) -> list[dict[str, str]]:
    label = _volume_label(volume)
    node_tree = _format_volume_node_tree(requirements, volume)
    skeleton_block = (
        volume_skeleton.strip()
        or f"# {requirements.project_name or '投标项目'} {label}\n\n{node_tree}"
    )
    user_prompt = f"""## 任务
修订{label}卷，补齐漏项、修正格式、删除越卷内容和元话语。你不是重新生成整份标书，只改需要改的地方。

## 本卷确定性骨架（来自招标文件投标文件格式，必须逐字保留）
{skeleton_block}

## 节点清单（用于核对标题、顺序和层级）
{node_tree}

项目名称：{requirements.project_name or "投标项目"}
投标人：{company_name}

### 总审打回修改意见
{audit_feedback or "- 首轮修订：补齐漏项、删除越卷内容、修正生成器语气。"}

### 招标文件格式要求
{requirements.bid_format_requirements or "- 未提取到格式要求。"}

### 分卷任务边界
{framework_brief or build_bid_framework_brief(requirements, document_outline)}

### 招标文件关键内容
{_format_tender_text(tender_text)}

### 规则（同初稿规则，优先级不变）
1. 节点不可变——以上确定性骨架是唯一结构，不得增删改任何节点标题
2. 表单照抄——优先保留确定性骨架里的招标文件原文模板；骨架缺原文时再从招标文件关键内容找模板原文逐字复制，只替换公司名→{company_name}
3. 方案自由写——施工内容连贯论述，每节≥2段
4. 不知道的留空——无依据字段留"________"，不编造，不写"人工确认点"

## 待修订初稿
{draft_markdown}

## 输出
只输出修订后的完整{label}卷 Markdown。第一行必须与【本卷确定性骨架】第一行一致。你必须先比对骨架和待修订初稿——如果初稿缺失了骨架中的任何标题节点，从骨架原样复制该节点（含标题层级和空白位），不得跳过。包括"其他内容""其他材料"类兜底节点必须保留标题占位。删除越卷表单。不输出解释。
"""
    return [
        {"role": "system", "content": GENERATOR_WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_structure_audit_prompt(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    commercial_markdown: str,
    technical_markdown: str,
    pricing_markdown: str,
) -> list[dict[str, str]]:
    """Pass 1 audit: format outline tree match only. No content inspection."""
    tree_text = _format_outline_tree(requirements.format_outline_tree)
    user_prompt = f"""## 任务
对比招标文件格式目录树与三卷实际生成的标题结构。只查结构（节点数量、标题名、层级、归属卷），不读正文内容。

## 唯一标准
以下节点树是唯一允许的结构，不得多、不得少、不得放错卷：
{tree_text or "未能提取格式目录树，跳过结构审计"}

## 三卷实际结构（只提取前 3000 字符查看标题层级）
== 商务/资格卷 ==
{commercial_markdown[:3000]}
== 技术卷 ==
{technical_markdown[:3000]}
== 报价/经济卷 ==
{pricing_markdown[:3000]}

## 判断规则
- pass：三卷标题结构完全匹配标准树（节点数量、名称、层级、归属卷全部一致）。
- revise：任何差异→逐条标注。

## 输出
只输出合法 JSON，不要 Markdown、不要代码块、不要解释：
{{
  "status": "pass" 或 "revise",
  "summary": "一句话结构审查结论",
  "issues": [
    {{
      "volume": "commercial" 或 "technical" 或 "pricing",
      "problem": "缺失节点 / 多余节点 / 层级错位 / 放错卷",
      "expected": "招标文件要求的是什么",
      "actual": "生成的是什么",
      "revision_prompt": "给该卷 Agent 的结构修改指令，只说怎么改结构，不说怎么写内容"
    }}
  ]
}}
status=revise 时 issues 不能为空——必须逐条标 volume+problem+expected+actual+revision_prompt。revision_prompt 只写结构修改指令，不得涉及内容质量或废标风险。
"""
    return [
        {"role": "system", "content": GENERATION_AUDITOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_generation_audit_prompt(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, Any]],
    framework_brief: str = "",
    commercial_markdown: str,
    technical_markdown: str,
    pricing_markdown: str,
    tender_text: str = "",
) -> list[dict[str, str]]:
    project_name = requirements.project_name or "投标项目"
    user_prompt = f"""## 任务
三卷结构已通过 Pass 1。现在审查内容：废标风险遗漏、AI 元文本、编造数据、越卷内容。你不是合稿 Agent，不输出修改后的标书正文——只判断 pass/revise 并给出修改指令。

项目名称：{project_name}
投标人：{company_name}

## 要检查的三卷
### 商务/资格卷
{commercial_markdown}

### 技术卷
{technical_markdown}

### 报价/经济卷
{pricing_markdown}

## 对照标准
### 招标文件格式要求
{requirements.bid_format_requirements or "- 未提取到格式要求。"}

### 招标文件全文
{_format_tender_text(tender_text)}

## 检查项
1. 废标/否决遗漏：资格要求全部响应？必填表单内容不为空？→ critical
2. AI 元文本："人工确认点""待补充""TODO""以下为AI生成""评分点摘要"等→ critical
3. 编造事实：金额/人名/证号/日期无依据→应留"________"→ critical
4. 越卷内容：本卷出现其他卷的表单或内容→ critical

## 输出
只输出合法 JSON，不要 Markdown、不要代码块、不要解释：
{{
  "status": "pass" 或 "revise",
  "summary": "一句话审查结论",
  "issues": [
    {{
      "volume": "commercial" 或 "technical" 或 "pricing" 或 "all",
      "severity": "critical" 或 "major" 或 "minor",
      "problem": "发现的问题",
      "revision_prompt": "给该分卷 Agent 的具体修改指令"
    }}
  ]
}}
通过条件：无废标/否决遗漏；无 AI 元文本；无编造事实；必填表单不为空。status=revise 时 issues 不能为空。
"""
    return [
        {"role": "system", "content": GENERATION_AUDITOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_bid_framework_brief(
    requirements: TenderRequirements,
    document_outline: list[dict[str, Any]],
) -> str:
    """Summarise the tender-native bid frame before dispatching volume agents."""
    volume_lines: dict[str, list[str]] = {
        "commercial": [],
        "technical": [],
        "pricing": [],
    }

    def walk(items: list[dict[str, Any]], inherited_volume: str = "") -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            volume = str(item.get("volume") or inherited_volume or "")
            label = _outline_volume_key(
                " ".join(
                    str(item.get(key) or "")
                    for key in ("title", "volume", "section_type")
                )
                + f" {volume}"
            )
            title = str(item.get("title") or "").strip()
            if title:
                volume_lines[label].append(title)
            children = item.get("children") or []
            if isinstance(children, list):
                walk(children, volume)

    walk(document_outline)
    lines = [
        "框架来源：招标文件格式要求 + 人工确认目录；该框架优先于风格案例和知识库。",
        "分卷任务边界：",
    ]
    for key, label in (
        ("commercial", "商务/资格卷"),
        ("technical", "技术卷"),
        ("pricing", "报价/经济卷"),
    ):
        titles = _dedupe_text(volume_lines[key])
        lines.append(
            f"- {label}：{'、'.join(titles[:30]) if titles else '本卷无明确节点；不得自行增加越卷表单。'}"
        )
    lines.extend(
        [
            "强制规则：",
            "- 三个分卷 Agent 只能生成自己分配到的节点，不得互相补写。",
            "- 同名表单必须按卷册归属区分；双信封项目允许商务及技术文件和报价文件分别存在投标函。",
            "- 系统负责最终拼接和 DOCX 分卷标记，任何 Agent 不得输出内部 marker 或合稿说明。",
        ]
    )
    return "\n".join(lines)


def _format_outline_tree(tree: dict[str, list[Any]], indent: int = 0) -> str:
    """Render a format outline tree as indented ASCII-like text."""
    import json

    if not tree:
        return "- 未提取到格式目录树；按人工确认目录生成。"

    volume_labels = {"commercial": "商务文件", "technical": "技术文件", "pricing": "报价文件"}
    lines: list[str] = []

    for vol_key, vol_label in volume_labels.items():
        nodes = tree.get(vol_key, [])
        if not nodes:
            continue
        lines.append(f"{vol_label}")
        for node in nodes:
            if isinstance(node, dict):
                title = node.get("title", "")
                children = node.get("children", [])
            else:
                title = getattr(node, "title", "")
                children = getattr(node, "children", [])
            if not title:
                continue
            # Skip root container nodes (e.g. '投标文件（商务文件）')
            # — only render children, which are the actual forms/sections.
            if children and "投标文件" in title:
                for child in children:
                    if isinstance(child, dict):
                        child_title = child.get("title", "")
                        grand_children = child.get("children", [])
                    else:
                        child_title = getattr(child, "title", "")
                        grand_children = getattr(child, "children", [])
                    if not child_title:
                        continue
                    if grand_children:
                        lines.append(f"│   ├── {child_title}")
                        for gc in grand_children:
                            gc_title = gc.get("title", "") if isinstance(gc, dict) else getattr(gc, "title", "")
                            if gc_title:
                                lines.append(f"│   │   └── {gc_title}")
                    else:
                        lines.append(f"│   └── {child_title}")
            else:
                lines.append(f"└── {title}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_items(items: list[str]) -> str:
    if not items:
        return "- 未明确"
    return "\n".join(f"- {item}" for item in items)


def _format_outline(document_outline: list[dict[str, Any]]) -> str:
    if not document_outline:
        return "- 系统未传入确认目录，请使用商务标、技术标、报价文件三卷完整结构。"

    lines: list[str] = []

    def walk(items: list[dict[str, Any]], depth: int = 0) -> None:
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            volume = str(item.get("volume") or "").strip()
            section_type = str(item.get("section_type") or "").strip()
            suffix = "；".join(part for part in (volume, section_type) if part)
            indent = "  " * depth
            lines.append(f"{indent}- {title}" + (f"（{suffix}）" if suffix else ""))
            children = item.get("children") or []
            if isinstance(children, list):
                walk(children, depth + 1)

    walk(document_outline)
    return "\n".join(lines) if lines else "- 系统未传入确认目录。"


def _format_volume_outline(document_outline: list[dict[str, Any]], volume: str) -> str:
    selected: list[dict[str, Any]] = []

    def walk(items: list[dict[str, Any]], parent_matches: bool = False) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            matches = _outline_item_matches_volume(item, volume) or parent_matches
            children = item.get("children") or []
            if matches:
                selected.append(item)
            if isinstance(children, list):
                walk(children, matches)

    walk(document_outline)
    return _format_outline(selected) if selected else _fallback_volume_outline(volume)


def _outline_item_matches_volume(item: dict[str, Any], volume: str) -> bool:
    text = " ".join(
        str(item.get(key) or "") for key in ("title", "volume", "section_type")
    )
    return _outline_volume_key(text) == volume


def _format_volume_node_tree(requirements: TenderRequirements, volume: str) -> str:
    """Render the format_outline_tree for a single volume as an exact node list.
    Only skips the root container (e.g. '投标文件（商务文件）'), not forms
    that happen to have sub-items.
    """
    nodes = requirements.format_outline_tree.get(volume, [])
    if not nodes:
        return f"- 未提取到{_VOLUME_LABELS.get(volume, volume)}格式树；按人工确认目录和格式要求生成。"

    lines: list[str] = []
    for node in nodes:
        title = node.title if hasattr(node, "title") else node.get("title", "")
        children = node.children if hasattr(node, "children") else node.get("children", [])
        # Only skip root container headings like "投标文件（商务文件）"
        # that merely group the volume's forms — NOT real forms with sub-items.
        if children and "投标文件" in title:
            for child in children:
                _render_node(child, lines, indent=0)
        else:
            _render_node(node, lines, indent=0)
    return "\n".join(lines)


def _render_node(node: Any, lines: list[str], indent: int) -> None:
    """Recursively render a format tree node."""
    title = node.title if hasattr(node, "title") else node.get("title", "")
    children = node.children if hasattr(node, "children") else node.get("children", [])
    prefix = "  " * indent + "- "
    lines.append(f"{prefix}{title}")
    for child in children:
        _render_node(child, lines, indent + 1)


def _outline_volume_key(text: str) -> str:
    if any(keyword in text for keyword in ("报价", "经济", "清单", "price")):
        return "pricing"
    if any(
        keyword in text for keyword in ("技术", "施工组织", "施工方案", "附图", "附表", "appendix")
    ):
        return "technical"
    return "commercial"


def _dedupe_text(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"\s+", "", item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fallback_volume_outline(volume: str) -> str:
    if volume == "pricing":
        return "- 报价文件\n  - 投标总价\n  - 已标价工程量清单\n  - 报价编制说明"
    if volume == "technical":
        return "- 技术文件\n  - 施工组织设计\n  - 附图附表"
    return "- 商务/资格文件\n  - 投标函\n  - 法定代表人身份证明或授权委托书\n  - 资格审查资料\n  - 投标保证金\n  - 承诺函"


def _filter_chunks_for_volume(
    chunks: list[dict[str, Any]],
    volume: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for chunk in chunks:
        section = str(chunk.get("section_title") or "")
        title = str(chunk.get("title") or "")
        content = str(chunk.get("content") or "")
        text = f"{section} {title} {content[:240]}"
        if _text_matches_volume(text, volume):
            selected.append(chunk)
    return selected or chunks[:8]


def _text_matches_volume(text: str, volume: str) -> bool:
    if volume == "pricing":
        return any(keyword in text for keyword in ("报价", "清单", "投标总价", "计价"))
    if volume == "technical":
        return any(keyword in text for keyword in ("施工", "技术", "质量", "安全", "环保", "进度"))
    return any(
        keyword in text for keyword in ("商务", "资格", "证书", "营业执照", "授权", "保证金", "承诺")
    )


_VOLUME_LABELS = {"commercial": "商务文件", "technical": "技术文件", "pricing": "报价文件"}


def _volume_label(volume: str) -> str:
    return _VOLUME_LABELS.get(volume, volume)


def _volume_agent_profile(volume: str) -> str:
    if volume == "pricing":
        return "你是报价文件合规主笔，熟悉工程量清单、计价规范、投标总价扉页和报价编制说明。你的任务是生成报价卷的目录、依据和响应说明；没有正式清单和造价数据时必须留空白，不得编造金额。"
    if volume == "technical":
        return (
            "你是技术标/施工组织设计主笔，熟悉施工部署、主要施工方案、进度、质量、安全、环保、文明施工、应急和附图附表。你的任务是写出有项目针对性的技术标成稿。"
        )
    return "你是商务/资格文件合规主笔，熟悉投标函、法人授权、资格审查、保证金、承诺函、企业资料和电子标上传格式。你的任务是按招标文件格式生成商务/资格卷。"


def _format_long_context_chunks(chunks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(chunks[:24], start=1):
        content = redact_pii(_clean_chunk(str(chunk.get("content") or "")))
        if not content:
            continue
        metadata = chunk.get("metadata") or {}
        title = chunk.get("title") or metadata.get("file_name") or f"企业资料 {index}"
        section = chunk.get("section_title") or "未指定章节"
        lines.append(f"[资料 {index}] 标题：{title}；适用章节：{section}\n{content[:1800]}")
    return "\n\n".join(lines)


def _format_bid_plan(bid_plan: dict[str, Any] | None) -> str:
    if not bid_plan:
        return "- 未传入 BidPlan；请以确认目录、招标要求和已选资料为准。"
    sections = bid_plan.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return "- BidPlan 未包含章节计划；请以确认目录、招标要求和已选资料为准。"
    lines: list[str] = []
    for section in sections[:30]:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if not title:
            continue
        chunk_ids = section.get("evidence_chunk_ids") or []
        image_ids = section.get("image_document_ids") or []
        table_required = section.get("table_required")
        notes = section.get("notes") or section.get("writing_notes") or ""
        parts = [f"- {title}"]
        if chunk_ids:
            parts.append(f"文本资料 chunk_id={','.join(str(v) for v in chunk_ids[:8])}")
        if image_ids:
            parts.append(f"图片 document_id={','.join(str(v) for v in image_ids[:8])}")
        if table_required:
            parts.append("需要表格")
        if notes:
            parts.append(str(notes)[:160])
        lines.append("；".join(parts))
    return "\n".join(lines) if lines else "- BidPlan 未包含可读章节计划。"


def _format_tender_text(tender_text: str) -> str:
    text = _clean_chunk(tender_text or "")
    if not text:
        return "- 当前项目未保存招标全文；只能依据解析 JSON 和已选资料生成。"

    keywords = (
        "项目名称",
        "工程名称",
        "招标范围",
        "建设地点",
        "计划工期",
        "工期",
        "质量",
        "安全",
        "环保",
        "文明施工",
        "施工组织",
        "评分",
        "技术",
        "资格",
        "否决",
        "废标",
        "工程量",
        "清单",
        "图纸",
        "公路",
        "道路",
        "桥梁",
        "管网",
        "交通",
        # 投标文件格式/组成要求：招标文件对商务卷表单和编排的规定必须进上下文
        "格式",
        "投标函",
        "投标文件的组成",
        "编制要求",
        "装订",
        "密封",
        "签字",
        "盖章",
        "授权委托",
        "承诺",
        "声明",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    selected_length = 0
    for line in lines:
        if any(keyword in line for keyword in keywords):
            selected.append(line)
            selected_length += len(line) + 1
        if selected_length >= 14000:
            break
    if not selected:
        selected = lines[:220]
    excerpt = "\n".join(selected)
    return excerpt[:18000]


def _format_pricing_strategy(pricing_strategy: dict[str, Any] | None) -> str:
    if not pricing_strategy:
        return "- 未提取到明确商务/报价约束；报价数值均留空白，按招标文件和工程量清单人工复核。"
    lines: list[str] = []

    def append_conditions(label: str, values: list[Any]) -> None:
        if not values:
            return
        lines.append(f"{label}：")
        for value in values[:5]:
            if isinstance(value, dict):
                text = value.get("source_text") or value.get("name") or str(value)
            else:
                text = str(value)
            lines.append(f"- {text}")

    # 工期/报价约束没有独立字段，存放在 extracted_conditions 里按 name 区分。
    extracted = [
        item
        for item in (pricing_strategy.get("extracted_conditions") or [])
        if isinstance(item, dict)
    ]
    append_conditions("付款条件", pricing_strategy.get("payment_terms") or [])
    append_conditions("保证金/担保要求", pricing_strategy.get("guarantee_requirements") or [])
    append_conditions(
        "工期要求",
        [item for item in extracted if "工期" in str(item.get("name", ""))],
    )
    append_conditions(
        "报价约束",
        [item for item in extracted if "报价" in str(item.get("name", ""))],
    )

    manual_fields = [
        field
        for field in (pricing_strategy.get("manual_fields") or [])
        if isinstance(field, dict) and field.get("label")
    ]
    if manual_fields:
        lines.append("必须留空白线（________）由人工填写的字段：")
        for field in manual_fields[:8]:
            reason = str(field.get("reason") or "").strip()
            label = str(field.get("label") or "").strip()
            lines.append(f"- {label}" + (f"（{reason}）" if reason else ""))

    return "\n".join(lines) if lines else "- 报价数值均留空白，按招标文件和工程量清单人工复核。"


def _format_knowledge_images(
    knowledge_images: list[dict[str, object]] | None,
) -> str:
    if not knowledge_images:
        return "【可插入知识库图片资料】\n- 暂无。"
    lines = [
        "【可插入知识库图片资料】",
        "以下图片来自企业知识库，可在资格资料、人员证件、业绩证明、附图附表等需要展示原件扫描件的位置插入；只能使用这些 document_id：",
    ]
    for image in knowledge_images[:12]:
        document_id = image.get("document_id")
        caption = image.get("caption") or image.get("file_name") or "知识库图片资料"
        file_name = image.get("file_name") or ""
        tags = image.get("tags") or []
        tag_text = (
            "、".join(str(tag) for tag in tags[:4]) if isinstance(tags, list) else ""
        )
        lines.append(
            f'- document_id={document_id}；caption="{caption}"；file="{file_name}"；tags="{tag_text}"；插入标记：{{{{knowledge_image:document_id={document_id} caption="{caption}"}}}}'
        )
    return "\n".join(lines)
