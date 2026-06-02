from __future__ import annotations

from openai import OpenAI

from agents.parser_agent import _has_real_key
from core.config import get_settings
from prompts.generator_prompt import build_section_prompt
from rag.retriever import RetrievalResult
from schemas.bid import BidSectionOutline
from schemas.tender import RequirementItem, TenderRequirements


class GeneratorAgentError(RuntimeError):
    pass


DEFAULT_SECTION_TITLES = [
    "施工总体部署",
    "施工组织设计",
    "质量保证措施",
    "进度计划与工期保证",
    "安全文明施工措施",
    "项目管理机构与人员配置",
    "废标风险响应",
]


SECTION_KEYWORDS = {
    "施工总体部署": ("总体", "部署", "现场", "施工方案"),
    "施工组织设计": ("施工组织设计", "施工方案", "技术方案"),
    "质量保证措施": ("质量", "验收", "标准"),
    "进度计划与工期保证": ("进度", "工期", "计划"),
    "安全文明施工措施": ("安全", "文明", "环保"),
    "项目管理机构与人员配置": ("人员", "项目经理", "项目总工", "组织机构"),
    "废标风险响应": ("否决", "废标", "无效", "重大偏差"),
}


def build_bid_outline(requirements: TenderRequirements) -> list[BidSectionOutline]:
    outlines: list[BidSectionOutline] = []
    seen_titles: set[str] = set()

    for item in requirements.technical_score_items:
        title = _section_title_for_item(item)
        if title in seen_titles:
            _append_focus(outlines, title, item.description)
            continue
        outlines.append(
            BidSectionOutline(
                title=title,
                required=True,
                source_item=item.title,
                focus_points=[item.description],
            )
        )
        seen_titles.add(title)

    for title in DEFAULT_SECTION_TITLES:
        if title not in seen_titles:
            outlines.append(BidSectionOutline(title=title, required=True))
            seen_titles.add(title)

    return outlines


def generate_bid_document(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
) -> str:
    outline = build_bid_outline(requirements)
    parts = [f"# {requirements.project_name or '技术标书初稿'}", ""]
    for section in outline:
        chunks = retrieved_chunks_by_section.get(section.title, [])
        parts.append(
            generate_bid_section(
                section.title,
                requirements,
                [_chunk_content(chunk) for chunk in chunks],
            )
        )
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def generate_bid_section(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> str:
    try:
        return _generate_section_with_llm(section_title, requirements, retrieved_chunks)
    except Exception:
        return _generate_section_fallback(section_title, requirements, retrieved_chunks)


def _generate_section_with_llm(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> str:
    settings = get_settings()
    if _has_real_key(settings.openrouter_api_key):
        api_key = settings.openrouter_api_key
        base_url = settings.openrouter_base_url
        model = settings.openrouter_model
    elif _has_real_key(settings.deepseek_api_key):
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model = settings.deepseek_model
    else:
        raise GeneratorAgentError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=build_section_prompt(section_title, requirements, retrieved_chunks),
        temperature=0.2,
        max_tokens=1800,
    )
    if not response.choices:
        raise GeneratorAgentError("LLM response did not contain choices")
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise GeneratorAgentError("LLM response was empty")
    if not content.startswith("##"):
        content = f"## {section_title}\n\n{content}"
    return content


def _generate_section_fallback(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
) -> str:
    project_name = requirements.project_name or "本项目"
    relevant_requirements = _relevant_requirement_text(section_title, requirements)
    knowledge_text = "\n".join(
        f"- {chunk[:180].strip()}" for chunk in retrieved_chunks[:3] if chunk.strip()
    )
    if not knowledge_text:
        knowledge_text = "- 暂无企业知识库依据，采用通用施工管理措施。"

    risk_items = "\n".join(
        f"- {item.description}" for item in requirements.invalid_bid_items[:3]
    )
    if not risk_items:
        risk_items = "- 招标文件未解析出明确废标条款，按通用合规要求执行。"

    return f"""## {section_title}

{project_name}的“{section_title}”章节围绕招标文件评分要求展开，重点回应施工部署、资源组织、过程控制和验收管理要求，确保技术方案与评审关注点一致。

### 招标要求响应
{relevant_requirements}

### 实施措施
- 建立项目经理负责制，明确技术、质量、安全、进度和资料管理职责。
- 编制专项实施计划，按关键节点跟踪资源投入、工序衔接和风险处置。
- 对涉及验收、旁站、隐蔽工程和资料归档的环节设置复核机制。

### 知识库依据
{knowledge_text}

### 合规风险控制
{risk_items}
"""


def _section_title_for_item(item: RequirementItem) -> str:
    combined = f"{item.title} {item.description}"
    for section_title, keywords in SECTION_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return section_title
    return item.title or "技术响应措施"


def _append_focus(
    outlines: list[BidSectionOutline],
    title: str,
    description: str,
) -> None:
    for outline in outlines:
        if outline.title == title and description:
            outline.focus_points.append(description)
            return


def _relevant_requirement_text(
    section_title: str,
    requirements: TenderRequirements,
) -> str:
    items = [
        item.description
        for item in requirements.technical_score_items
        if _section_title_for_item(item) == section_title
    ]
    if not items:
        items = [item.description for item in requirements.technical_score_items[:3]]
    if not items:
        return "- 招标文件未解析出具体技术评分项，本章节按常规技术标要求响应。"
    return "\n".join(f"- {item}" for item in items)


def _chunk_content(chunk: RetrievalResult | str) -> str:
    if isinstance(chunk, str):
        return chunk
    return chunk.content
