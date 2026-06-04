from __future__ import annotations

from openai import OpenAI

from agents.parser_agent import _has_real_key, _is_placeholder_project_name
from core.config import get_settings
from prompts.generator_prompt import build_document_prompt, build_section_prompt
from rag.retriever import RetrievalResult
from schemas.bid import BidSectionOutline
from schemas.tender import RequirementItem, TenderRequirements


class GeneratorAgentError(RuntimeError):
    pass


BID_TEMPLATE_SECTION_TITLES = [
    "第一章、总体施工组织布置及规划",
    "第二章、主要工程项目的施工方案、方法与技术措施",
    "第三章、工期保证体系及保证措施",
    "第四章、工程质量管理体系及保证措施",
    "第五章、安全生产管理体系及保证措施",
    "第六章、环境保护、水土保持保证体系及保证措施",
    "第七章、文明施工、文物保护保证体系及保证措施",
    "第八章、项目风险预测与防范，事故应急预案",
    "第九章、其他应说明的事项",
]
DEFAULT_SECTION_TITLES = BID_TEMPLATE_SECTION_TITLES
MAX_OUTLINE_SECTIONS = len(BID_TEMPLATE_SECTION_TITLES)


SECTION_KEYWORDS = {
    "第一章、总体施工组织布置及规划": (
        "总体",
        "组织",
        "布置",
        "规划",
        "部署",
        "概况",
        "目标",
    ),
    "第二章、主要工程项目的施工方案、方法与技术措施": (
        "主要工程",
        "施工方案",
        "施工方法",
        "技术措施",
        "重点",
        "关键",
        "难点",
        "道路",
        "路基",
        "路面",
        "护栏",
        "测量",
    ),
    "第三章、工期保证体系及保证措施": ("工期", "进度", "计划"),
    "第四章、工程质量管理体系及保证措施": ("质量", "验收", "标准"),
    "第五章、安全生产管理体系及保证措施": ("安全", "生产", "交安"),
    "第六章、环境保护、水土保持保证体系及保证措施": (
        "环境",
        "环保",
        "水土",
        "扬尘",
        "污染",
    ),
    "第七章、文明施工、文物保护保证体系及保证措施": (
        "文明",
        "文物",
        "现场管理",
    ),
    "第八章、项目风险预测与防范，事故应急预案": (
        "风险",
        "应急",
        "事故",
        "防范",
        "预案",
    ),
    "第九章、其他应说明的事项": ("其他", "说明", "补充"),
}


def build_bid_outline(requirements: TenderRequirements) -> list[BidSectionOutline]:
    outlines: list[BidSectionOutline] = [
        BidSectionOutline(title=title, required=True)
        for title in BID_TEMPLATE_SECTION_TITLES
    ]

    for item in requirements.technical_score_items:
        title = _section_title_for_item(item)
        _append_focus(outlines, title, item.description)

    return outlines[:MAX_OUTLINE_SECTIONS]


def generate_bid_document(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
) -> str:
    outline = build_bid_outline(requirements)
    settings = get_settings()
    use_local_section_fallback = False
    if settings.enable_llm_generation:
        try:
            markdown = _generate_document_with_llm(
                requirements,
                outline,
                retrieved_chunks_by_section,
                settings.company_name,
            )
            return _ensure_document_header(markdown, requirements, settings.company_name)
        except Exception:
            use_local_section_fallback = True
    else:
        use_local_section_fallback = True

    parts = [
        f"# {_project_title(requirements)} 投标文件（技术文件）",
        "",
        f"投标人：{settings.company_name}",
        "",
        "## 施工组织设计目录",
        "",
    ]
    for section in outline:
        parts.append(f"- {section.title}")
    parts.append("")
    for section in outline:
        chunks = retrieved_chunks_by_section.get(section.title, [])
        chunk_text = [_chunk_content(chunk) for chunk in chunks]
        if use_local_section_fallback:
            section_markdown = _generate_section_fallback(
                section.title,
                requirements,
                chunk_text,
            )
        else:
            section_markdown = generate_bid_section(
                section.title,
                requirements,
                chunk_text,
            )
        parts.append(
            section_markdown
        )
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _project_title(requirements: TenderRequirements) -> str:
    if requirements.project_name and not _is_placeholder_project_name(
        requirements.project_name
    ):
        return requirements.project_name
    return "投标项目"


def _ensure_document_header(
    markdown: str,
    requirements: TenderRequirements,
    company_name: str,
) -> str:
    title = f"# {_project_title(requirements)} 投标文件（技术文件）"
    lines = markdown.lstrip().splitlines()
    if not lines:
        lines = [title]
    elif lines[0].lstrip().startswith("#"):
        lines[0] = title
    else:
        lines = [title, "", *lines]

    has_company_name = any(company_name in line for line in lines[:12])
    if company_name and not has_company_name:
        insert_at = 1
        if len(lines) > 1 and lines[1].strip():
            lines.insert(insert_at, "")
            insert_at += 1
        lines.insert(insert_at, f"**投标人：{company_name}**")
        lines.insert(insert_at + 1, "")

    return "\n".join(lines).strip() + "\n"


def _generate_document_with_llm(
    requirements: TenderRequirements,
    outline: list[BidSectionOutline],
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    company_name: str,
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

    chunks = _flatten_retrieved_chunks(retrieved_chunks_by_section)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=35.0)
    response = client.chat.completions.create(
        model=model,
        messages=build_document_prompt(
            requirements=requirements,
            outline_titles=[section.title for section in outline],
            retrieved_chunks=chunks,
            company_name=company_name,
        ),
        temperature=0.2,
        max_tokens=6000,
        timeout=35.0,
    )
    if not response.choices:
        raise GeneratorAgentError("LLM response did not contain choices")
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise GeneratorAgentError("LLM response was empty")
    return content if content.endswith("\n") else content + "\n"


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

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=25.0)
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
    project_name = _project_title(requirements)
    relevant_requirements = _relevant_requirement_text(section_title, requirements)
    template_points = "\n".join(
        f"- {chunk[:260].strip()}" for chunk in retrieved_chunks[:3] if chunk.strip()
    )
    if not template_points:
        template_points = "- 参考企业既有公路工程投标文件的施工组织设计格式组织编写。"
    first_section, second_section = _fallback_subsections(section_title)

    return f"""## {section_title}

### 第一节、{first_section}

#### 一、编制原则
我单位针对{project_name}的招标文件要求、工程特点、工期目标、质量标准和安全目标进行综合分析，按照企业既有投标文件“施工组织设计”的编制深度组织本章节内容。本章节坚持“响应招标文件、结合现场条件、突出重点难点、保证履约落地”的原则，确保技术方案内容完整、措施明确、责任清晰。

#### 二、招标要求响应
{relevant_requirements}

#### 三、企业模板依据
{template_points}

### 第二节、{second_section}

#### 一、组织实施措施
本公司将组建高效、精干、专业配套的项目管理机构，实行项目经理负责制，统筹工程技术、质量安全、计划合约、物资设备和综合协调等工作。各专业施工队伍按施工区段和工序流水组织进场，做到人员、机械、材料和技术方案同步落实。

#### 二、过程控制措施
施工过程中严格执行技术交底、样板引路、过程检查、隐蔽验收、资料同步归档等管理制度。对涉及工期、质量、安全、环保和文明施工的关键节点，项目部实行日检查、周调度、月总结，发现偏差及时纠偏，确保各项承诺满足招标文件要求。

#### 三、风险与合规控制
针对招标文件列明的否决投标、重大偏差和实质性响应要求，我单位将在投标文件编制、施工准备、过程实施和交验收尾各阶段逐项复核，确保工期、质量、安全、资质、人员、设备、保证金及其他承诺均实质性响应招标文件。
"""


def _fallback_subsections(section_title: str) -> tuple[str, str]:
    mapping = {
        "第一章、总体施工组织布置及规划": ("工程概况描述", "施工总体部署"),
        "第二章、主要工程项目的施工方案、方法与技术措施": (
            "主要工程施工安排",
            "关键工序施工方法",
        ),
        "第三章、工期保证体系及保证措施": ("施工进度计划", "工期保证措施"),
        "第四章、工程质量管理体系及保证措施": ("质量管理体系", "质量保证措施"),
        "第五章、安全生产管理体系及保证措施": ("安全生产管理体系", "安全保证措施"),
        "第六章、环境保护、水土保持保证体系及保证措施": (
            "环境保护管理体系",
            "水土保持措施",
        ),
        "第七章、文明施工、文物保护保证体系及保证措施": (
            "文明施工管理体系",
            "文物保护措施",
        ),
        "第八章、项目风险预测与防范，事故应急预案": (
            "风险预测与防范",
            "事故应急预案",
        ),
        "第九章、其他应说明的事项": ("综合协调管理", "资料与交付管理"),
    }
    return mapping.get(section_title, ("施工组织安排", "保证措施"))


def _section_title_for_item(item: RequirementItem) -> str:
    combined = f"{item.title} {item.description}"
    for section_title, keywords in SECTION_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return section_title
    return "第二章、主要工程项目的施工方案、方法与技术措施"


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


def _flatten_retrieved_chunks(
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
) -> list[str]:
    chunks: list[str] = []
    seen: set[str] = set()
    for section_chunks in retrieved_chunks_by_section.values():
        for chunk in section_chunks:
            content = _chunk_content(chunk).strip()
            if not content or content in seen:
                continue
            chunks.append(content)
            seen.add(content)
            if len(chunks) >= 12:
                return chunks
    return chunks
