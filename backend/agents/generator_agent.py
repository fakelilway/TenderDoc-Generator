from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from agents.parser_agent import _has_real_key, _is_placeholder_project_name
from core.config import get_settings
from prompts.generator_prompt import build_long_context_prompt, build_section_prompt
from rag.retriever import RetrievalResult
from schemas.bid import BidDocumentOutlineSection, BidPackage, BidSectionOutline
from schemas.bid_plan import BidPlan
from schemas.bid_template import BidTemplate
from schemas.strategy import PricingStrategy
from schemas.tender import RequirementItem, TenderRequirements
from services.bid_tone_checker import line_has_forbidden_tone
from utils.docx_exporter import combine_delivery_volumes, split_delivery_markdown


class GeneratorAgentError(RuntimeError):
    pass


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
LONG_CONTEXT_MAX_CONTINUATIONS = 2


# --- Output hygiene -------------------------------------------------------
# Real bids never contain authoring meta-text or leaked source fragments, so
# the generated markdown is sanitised before it is shown / exported. Spots that
# need company data are left as a clean fill-in blank for the user to edit in
# the workspace, rather than an "人工确认点" annotation.
FILL_IN_BLANK = "________"
_MANUAL_MARK_RE = re.compile(r"⚠️?\s*人工确认点\s*[：:]\s*【待补充】\s*")
_PAGE_FOOTER_RE = re.compile(r"第\s*\d+\s*页\s*[/／共]?\s*\d*\s*页?")
_DOTS_ONLY_RE = re.compile(r"^[.·•・·。……\-—_=\s]+$")
_EMPTY_TABLE_ROW_RE = re.compile(r"^\s*\|(?:\s*\|)+\s*$")
_META_LINE_KEYWORDS = ("本章响应度自查", "响应度自查", "废标风险逐条响应自查表")


def sanitize_bid_markdown(markdown: str) -> str:
    """Strip authoring meta-text and leaked RAG fragments from bid markdown."""
    cleaned: list[str] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if any(keyword in stripped for keyword in _META_LINE_KEYWORDS):
            continue
        if line_has_forbidden_tone(stripped):
            continue
        if stripped and _PAGE_FOOTER_RE.fullmatch(stripped):
            continue
        if stripped and _DOTS_ONLY_RE.match(stripped):
            continue
        # A real bid form leaves an underline blank for the bidder to fill,
        # never an "人工确认点" annotation.
        line = _MANUAL_MARK_RE.sub(FILL_IN_BLANK, line)
        line = line.replace("【待补充】", FILL_IN_BLANK)
        line = line.replace("人工确认点", "").replace("⚠️", "")
        line = _PAGE_FOOTER_RE.sub("", line)
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = _EMPTY_TABLE_ROW_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


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


def load_bid_template(template_path: str | Path | None = None) -> BidTemplate | None:
    settings = get_settings()
    raw_path = template_path or getattr(settings, "bid_template_path", "")
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    if not path.exists():
        return None
    try:
        return BidTemplate.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_bid_outline(
    requirements: TenderRequirements,
    bid_template: BidTemplate | None = None,
) -> list[BidSectionOutline]:
    template_titles = _technical_titles_from_template(bid_template)
    source_titles = template_titles or BID_TEMPLATE_SECTION_TITLES
    outlines: list[BidSectionOutline] = [
        BidSectionOutline(title=title, required=True) for title in source_titles
    ]

    for item in requirements.technical_score_items:
        title = _section_title_for_item(item, [outline.title for outline in outlines])
        _append_focus(outlines, title, item.description)

    # BidTemplate JSON is the single structural authority when present. The
    # fallback section cap only applies when no real template is available.
    return outlines if template_titles else outlines[:MAX_OUTLINE_SECTIONS]


def build_bid_document_outline(
    requirements: TenderRequirements,
    bid_template: BidTemplate | None = None,
) -> list[BidDocumentOutlineSection]:
    """Build the complete bid package outline, not only construction design."""
    technical_outline = build_bid_outline(requirements, bid_template)
    technical_children = [
        BidDocumentOutlineSection(
            title=section.title,
            volume="技术标",
            section_type="construction_design",
            required=section.required,
            source_item=section.source_item,
            focus_points=section.focus_points,
        )
        for section in technical_outline
    ]
    if not bid_template or not bid_template.main_sections:
        return [
            BidDocumentOutlineSection(
                title="一、技术标",
                volume="技术标",
                section_type="technical_volume",
                children=technical_children,
            ),
            BidDocumentOutlineSection(
                title="二、商务标",
                volume="商务标",
                section_type="business_volume",
                children=[
                    BidDocumentOutlineSection(
                        title=title,
                        volume="商务标",
                        section_type="fixed_form",
                    )
                    for title in (
                        "投标函",
                        "授权委托书或法定代表人身份证明",
                        "资格审查资料",
                        "投标保证金",
                        "承诺函",
                    )
                ],
            ),
            BidDocumentOutlineSection(
                title="报价文件",
                volume="报价/经济标",
                section_type="price",
                focus_points=["报价金额、工程量清单和综合单价以正式清单数据为准。"],
            ),
        ]

    document_outline: list[BidDocumentOutlineSection] = []
    has_price_section = False
    for section in bid_template.main_sections:
        volume = _document_volume_for_section(section.title, section.section_type)
        if volume == "报价/经济标":
            has_price_section = True
        children = (
            technical_children if section.section_type == "construction_design" else []
        )
        document_outline.append(
            BidDocumentOutlineSection(
                title=section.title,
                volume=volume,
                section_type=section.section_type,
                required=True,
                source_item=section.source_page_label,
                children=children,
            )
        )

    if bid_template.appendix_sections:
        document_outline.append(
            BidDocumentOutlineSection(
                title="附图附表",
                volume="技术标",
                section_type="appendix_group",
                children=[
                    BidDocumentOutlineSection(
                        title=section.title,
                        volume="技术标",
                        section_type="appendix",
                        source_item=section.source_page_label,
                    )
                    for section in bid_template.appendix_sections
                ],
            )
        )

    if not has_price_section:
        document_outline.append(
            BidDocumentOutlineSection(
                title="报价文件（第二信封/经济标，如招标文件要求）",
                volume="报价/经济标",
                section_type="price_missing_template",
                required=False,
                source_item="当前模板未包含报价卷；如招标文件要求第二信封，需绑定报价模板或接入工程量清单。",
                focus_points=["投标总价、综合单价和清单合价以正式报价文件为准。"],
            )
        )
    return document_outline


def generate_bid_package(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    bid_template: BidTemplate | None = None,
    pricing_strategy: PricingStrategy | None = None,
    knowledge_images: list[dict[str, object]] | None = None,
    bid_plan: BidPlan | None = None,
    tender_text: str = "",
) -> BidPackage:
    bid_template = bid_template or load_bid_template()
    knowledge_images = _filter_knowledge_images_by_plan(knowledge_images, bid_plan)
    outline = build_bid_outline(requirements, bid_template)
    settings = get_settings()
    generation_mode = str(
        getattr(settings, "bid_generation_mode", "long_context") or "long_context"
    ).lower()
    if settings.enable_llm_generation and generation_mode in {
        "long_context",
        "simple",
        "auto",
    }:
        try:
            return generate_bid_package_long_context(
                requirements,
                retrieved_chunks_by_section,
                bid_template=bid_template,
                pricing_strategy=pricing_strategy,
                knowledge_images=knowledge_images,
                bid_plan=bid_plan,
                company_name=settings.company_name,
                tender_text=tender_text,
            )
        except Exception as error:
            if not getattr(settings, "bid_generation_fallback_enabled", True):
                raise
            # Keep the product usable when the long-context model call fails:
            # fall back to the established section pipeline and deterministic
            # business/pricing shells.
            logger.warning(
                "Long-context generation failed; falling back", exc_info=True
            )
            fallback_reason = str(error)
    else:
        fallback_reason = None
    use_local_section_fallback = False
    if not settings.enable_llm_generation:
        use_local_section_fallback = True
    else:
        # The current LLM path is section-oriented and safest for technical
        # writing. 商务/报价卷 use deterministic templates so they do not invent
        # business facts or prices.
        use_local_section_fallback = False

    commercial = _generate_commercial_volume(
        requirements,
        bid_template,
        pricing_strategy,
        settings.company_name,
        knowledge_images,
    )
    technical = _generate_technical_volume(
        requirements,
        outline,
        retrieved_chunks_by_section,
        bid_template,
        use_local_section_fallback,
        settings.company_name,
        knowledge_images,
        bid_plan,
    )
    pricing = _generate_pricing_volume(
        requirements,
        pricing_strategy,
        settings.company_name,
        missing_template=not _template_has_price_section(bid_template),
    )
    # The combined document carries lossless volume markers so it can later be
    # split back into the exact volumes (see utils.docx_exporter).
    combined = combine_delivery_volumes(
        f"{_project_title(requirements)} 投标文件",
        {
            "commercial": commercial,
            "technical": technical,
            "pricing": pricing,
        },
    )
    return BidPackage(
        commercial_markdown=commercial,
        technical_markdown=technical,
        pricing_markdown=pricing,
        combined_markdown=combined,
        generation_mode="local_fallback" if use_local_section_fallback else "section",
        fallback_reason=fallback_reason,
    )


def generate_bid_package_long_context(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    *,
    bid_template: BidTemplate | None = None,
    pricing_strategy: PricingStrategy | None = None,
    knowledge_images: list[dict[str, object]] | None = None,
    bid_plan: BidPlan | None = None,
    company_name: str | None = None,
    tender_text: str = "",
) -> BidPackage:
    """Generate the whole bid in one model call.

    This is the primary generation kernel for long-context models. Existing
    template/evidence/DOCX infrastructure remains the product shell around it.
    """
    bid_template = bid_template or load_bid_template()
    settings = get_settings()
    company_name = company_name or settings.company_name
    document_outline = [
        section.model_dump()
        for section in build_bid_document_outline(requirements, bid_template)
    ]
    knowledge_chunks = _long_context_chunks(retrieved_chunks_by_section)
    raw_markdown = _generate_long_context_with_llm(
        requirements=requirements,
        company_name=company_name,
        document_outline=document_outline,
        bid_plan=bid_plan,
        template_name=bid_template.template_name if bid_template else "",
        pricing_strategy=pricing_strategy,
        knowledge_chunks=knowledge_chunks,
        knowledge_images=knowledge_images,
        tender_text=tender_text,
    )
    raw_markdown = sanitize_bid_markdown(raw_markdown)
    volumes = split_delivery_markdown(raw_markdown)
    commercial = sanitize_bid_markdown(volumes.get("commercial", ""))
    technical = sanitize_bid_markdown(volumes.get("technical", ""))
    pricing = sanitize_bid_markdown(volumes.get("pricing", ""))
    combined = combine_delivery_volumes(
        f"{_project_title(requirements)} 投标文件",
        {
            "commercial": commercial,
            "technical": technical,
            "pricing": pricing,
        },
    )
    return BidPackage(
        commercial_markdown=commercial,
        technical_markdown=technical,
        pricing_markdown=pricing,
        combined_markdown=combined,
        generation_mode="long_context",
    )


def _generate_commercial_volume(
    requirements: TenderRequirements,
    bid_template: BidTemplate | None,
    pricing_strategy: PricingStrategy | None,
    company_name: str,
    knowledge_images: list[dict[str, object]] | None = None,
) -> str:
    parts = [
        f"# {_project_title(requirements)} 商务文件",
        "",
        f"投标人：{company_name}",
        "",
        "【商务文件】",
        "",
    ]
    emitted = False
    if bid_template and bid_template.main_sections:
        for section in bid_template.main_sections:
            if (
                _document_volume_for_section(section.title, section.section_type)
                == "商务/资格标"
            ):
                parts.extend(
                    _business_section_from_template(
                        requirements,
                        section,
                        pricing_strategy,
                        knowledge_images,
                    )
                )
                emitted = True
    if not emitted:
        fallback = _business_bid_fallback(
            requirements, pricing_strategy, bid_template, knowledge_images
        )
        parts.extend(fallback)
    return sanitize_bid_markdown("\n".join(parts).strip() + "\n")


def _generate_technical_volume(
    requirements: TenderRequirements,
    outline: list[BidSectionOutline],
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    bid_template: BidTemplate | None,
    use_local_section_fallback: bool,
    company_name: str,
    knowledge_images: list[dict[str, object]] | None = None,
    bid_plan: BidPlan | None = None,
) -> str:
    parts = _document_preface(requirements, company_name)
    parts[0] = f"# {_project_title(requirements)} 技术文件"
    parts[2] = f"投标人：{company_name}"
    parts.extend(["【技术文件】", ""])
    parts.extend(
        _technical_volume_from_outline(
            requirements,
            outline,
            retrieved_chunks_by_section,
            use_local_section_fallback,
            knowledge_images,
            bid_plan,
        )
    )
    if bid_template and bid_template.appendix_sections:
        parts.extend(_appendix_fallback(bid_template))
        parts.append("")
    return sanitize_bid_markdown("\n".join(parts).strip() + "\n")


def _generate_pricing_volume(
    requirements: TenderRequirements,
    pricing_strategy: PricingStrategy | None,
    company_name: str,
    *,
    missing_template: bool,
) -> str:
    parts = [
        f"# {_project_title(requirements)} 报价文件",
        "",
        f"投标人：{company_name}",
        "",
        "【报价文件】",
        "",
        *_price_bid_fallback(pricing_strategy, missing_template=missing_template),
    ]
    return sanitize_bid_markdown("\n".join(parts).strip() + "\n")


def _template_has_price_section(bid_template: BidTemplate | None) -> bool:
    if not bid_template:
        return False
    return any(
        _document_volume_for_section(section.title, section.section_type) == "报价/经济标"
        for section in bid_template.main_sections
    )


def _project_title(requirements: TenderRequirements) -> str:
    if requirements.project_name and not _is_placeholder_project_name(
        requirements.project_name
    ):
        return requirements.project_name
    return "投标项目"


def _document_preface(
    requirements: TenderRequirements,
    company_name: str,
) -> list[str]:
    project_name = _project_title(requirements)
    core_lines = _project_core_lines(requirements)
    return [
        f"# {project_name} 投标文件",
        "",
        f"投标人：{company_name}",
        "",
        "## 投标文件响应总说明",
        "",
        f"我单位已认真研究{project_name}招标文件、补遗澄清文件及相关技术资料，充分理解招标范围、资格条件、评审办法、合同条款、工期质量安全要求及否决投标条款。本投标文件按照招标文件和模板目录顺序编制，做到资格、商务、技术、报价及附表资料逐项响应，并对所提交资料的真实性负责。",
        "",
        *core_lines,
        "",
    ]


def _project_core_lines(requirements: TenderRequirements) -> list[str]:
    fields = [
        ("招标人", requirements.tenderer_name),
        ("建设地点", requirements.project_location),
        ("招标范围", requirements.tender_scope),
        ("计划工期", requirements.planned_duration),
        ("质量标准", requirements.quality_standard),
        ("安全目标", requirements.safety_target),
    ]
    lines = ["| 项目要素 | 响应内容 |", "| --- | --- |"]
    for label, value in fields:
        if value:
            lines.append(f"| {label} | {value} |")
    return lines if len(lines) > 2 else []


def _technical_volume_from_outline(
    requirements: TenderRequirements,
    outline: list[BidSectionOutline],
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    use_local_section_fallback: bool,
    knowledge_images: list[dict[str, object]] | None = None,
    bid_plan: BidPlan | None = None,
) -> list[str]:
    parts = ["## 五、施工组织设计", "", "### 施工组织设计目录", ""]
    for section in outline:
        parts.append(f"- {section.title}")
    parts.append("")
    if not outline:
        return parts

    def _render_section(section: BidSectionOutline) -> str:
        chunks = _filter_chunks_for_bid_plan(
            retrieved_chunks_by_section.get(section.title, []),
            bid_plan,
            section.title,
        )
        chunk_text = _bid_text_chunks(chunks)
        if use_local_section_fallback:
            return _generate_section_fallback(
                section.title,
                requirements,
                chunk_text,
            )
        if knowledge_images:
            return generate_bid_section(
                section.title,
                requirements,
                chunk_text,
                knowledge_images,
            )
        return generate_bid_section(
            section.title,
            requirements,
            chunk_text,
        )

    # Sections are independent, so the per-section LLM calls run concurrently;
    # results are re-assembled in outline order. Per-section failures still
    # fall back locally inside ``generate_bid_section``.
    with ThreadPoolExecutor(max_workers=min(4, len(outline))) as executor:
        section_markdowns = list(executor.map(_render_section, outline))
    for section_markdown in section_markdowns:
        parts.extend([section_markdown, ""])
    return parts


def _business_section_from_template(
    requirements: TenderRequirements,
    section,
    pricing_strategy: PricingStrategy | None,
    knowledge_images: list[dict[str, object]] | None = None,
) -> list[str]:
    payment_note, guarantee_note = _pricing_context_notes(pricing_strategy)
    body = _template_business_section_body(
        section.title,
        _project_title(requirements),
        _format_requirement_items(requirements.qualification_list),
        _format_requirement_items(requirements.invalid_bid_items),
        payment_note,
        guarantee_note,
        knowledge_images,
        requirements,
    )
    return [f"## {section.title}", "", *body, ""]


def _price_bid_fallback(
    pricing_strategy: PricingStrategy | None,
    missing_template: bool = False,
) -> list[str]:
    heading = "## 报价文件"
    if missing_template:
        heading = "## 报价文件（第二信封/经济标，如招标文件要求）"
    lines = [
        heading,
        "",
        "本报价文件依据招标文件、工程量清单、施工图纸、补遗澄清文件、现行计价规范及企业施工组织安排编制。投标报价包括完成本项目招标范围内全部工程内容所需的人工、材料、机械、管理、利润、规费、税金、风险及合同约定的其他费用。",
        "",
        "报价文件目录如下：",
        "- 投标总价",
        "- 已标价工程量清单",
        "- 分部分项工程量清单计价表",
        "- 措施项目清单计价表",
        "- 其他项目清单计价表",
        "- 主要材料、设备价格表",
        "- 报价编制说明",
        "",
    ]
    payment_note, guarantee_note = _pricing_context_notes(pricing_strategy)
    if payment_note:
        lines.extend([payment_note, ""])
    if guarantee_note:
        lines.extend([guarantee_note, ""])
    return lines


def _pricing_context_notes(
    pricing_strategy: PricingStrategy | None,
) -> tuple[str, str]:
    payment_note = ""
    guarantee_note = ""
    if pricing_strategy:
        if pricing_strategy.payment_terms:
            snippets = [
                condition.source_text or condition.name
                for condition in pricing_strategy.payment_terms[:3]
            ]
            if snippets:
                payment_note = "本项目付款及合同商务条件摘要（须以招标文件原文复核）：" + "；".join(snippets)
        if pricing_strategy.guarantee_requirements:
            snippets = [
                condition.source_text or condition.name
                for condition in pricing_strategy.guarantee_requirements[:3]
            ]
            if snippets:
                guarantee_note = "本项目担保/保证金条款摘要（须以招标文件原文复核）：" + "；".join(snippets)
    return payment_note, guarantee_note


def _document_volume_for_section(title: str, section_type: str) -> str:
    combined = f"{title} {section_type}"
    if any(keyword in combined for keyword in ("报价", "清单", "投标总价", "price")):
        return "报价/经济标"
    if section_type == "construction_design" or "施工组织设计" in title:
        return "技术标"
    if section_type == "appendix":
        return "技术标"
    return "商务/资格标"


def _business_bid_fallback(
    requirements: TenderRequirements,
    pricing_strategy: PricingStrategy | None = None,
    bid_template: BidTemplate | None = None,
    knowledge_images: list[dict[str, object]] | None = None,
) -> list[str]:
    project_name = _project_title(requirements)
    qualification_text = _format_requirement_items(requirements.qualification_list)
    invalid_bid_text = _format_requirement_items(requirements.invalid_bid_items)

    payment_note = ""
    guarantee_note = ""
    if pricing_strategy:
        if pricing_strategy.payment_terms:
            snippets = [
                c.source_text[:80]
                for c in pricing_strategy.payment_terms[:2]
                if c.source_text
            ]
            if snippets:
                payment_note = "本项目付款条件摘要（须人工核实原文）：" + "；".join(snippets)
        if pricing_strategy.guarantee_requirements:
            snippets = [
                c.source_text[:80]
                for c in pricing_strategy.guarantee_requirements[:2]
                if c.source_text
            ]
            if snippets:
                guarantee_note = "本项目担保/保证金条款摘要（须人工核实原文）：" + "；".join(snippets)

    if bid_template and bid_template.fixed_form_sections:
        return _business_bid_from_template(
            requirements,
            bid_template,
            payment_note=payment_note,
            guarantee_note=guarantee_note,
            knowledge_images=knowledge_images,
        )

    parts: list[str] = [
        "【商务标】",
        "",
        "## 二、商务标",
        "",
        "### 1. 投标函及投标函附录",
        "",
        f"致：{requirements.tenderer_name or '________'}（招标人名称）",
        "",
        f"1. 我方经详细研究{project_name}招标文件及相关资料，决定参加本项目投标，并承诺按招标文件、合同条款、技术标准和工程量清单要求完成全部工作内容。",
        "2. 本次投标总报价为________元（大写：________整），具体金额以已标价工程量清单为准。",
        f"3. 我方承诺的工期严格响应招标文件要求（{requirements.planned_duration or '________'}）；工程质量标准达到招标文件规定的{requirements.quality_standard or '合格及以上等级'}。",
        "4. 我方承诺在投标有效期内不撤销投标文件，不修改投标实质性内容；如中标，将按招标文件规定的时限和方式提交履约担保并签订合同。",
    ]
    if payment_note:
        parts += ["", payment_note]
    parts += [
        "",
        "投标函附录包括项目名称、投标人名称、投标报价、工期、质量标准、项目经理、投标有效期、权利义务响应等内容；涉及具体数值和人员信息须依据企业真实资料填写。",
        "",
        "### 2. 法定代表人身份证明及授权委托书",
        "",
        "1. 法定代表人身份证明应载明投标人名称、统一社会信用代码、法定代表人姓名、职务、身份证号码，并附身份证复印件或扫描件。",
        "2. 授权委托书应明确授权代理人代表投标人办理本项目投标、澄清、签署文件等事项，授权期限覆盖投标有效期。",
        "3. 以下信息须依据企业真实资料填写：法定代表人姓名（________）、身份证号（________）、授权代理人姓名（________）、身份证号（________）、授权期限（________）及签章页扫描件。",
        "",
        "### 3. 资格审查资料",
        "",
        "资格审查资料按招标文件要求编制，至少包括以下内容：",
        "",
        "1. 企业营业执照、资质证书、安全生产许可证及其他行政许可文件。",
        "2. 项目经理注册建造师证书、安全生产考核合格证书、无在建承诺及社保证明。",
        "3. 技术负责人职称证书、专职安全员证书及主要管理人员岗位证书。",
        "4. 类似业绩证明材料，包括中标通知书、合同协议书、竣工验收或交工验收证明等。",
        "5. 财务、信誉、信用平台查询、无重大违法记录等招标文件要求的其他证明资料。",
        "",
        "招标文件资格要求响应如下：",
        qualification_text,
        "",
        "注：企业资质证书编号（________）、人员证书编号（________）、社保证明、类似业绩项目名称（________）及合同金额（________元）须使用企业真实资料，并附扫描件或复印件。",
        "",
        *_knowledge_image_block(
            knowledge_images,
            keywords=("营业执照", "资质", "安全生产", "建造师", "身份证", "建安", "交安", "职称", "社保", "业绩"),
        ),
        "",
        "### 4. 报价文件",
        "",
        "本报价文件依据招标文件、工程量清单、施工图纸、补遗澄清文件、现行计价规范及企业施工组织安排编制。投标报价包括完成本项目招标范围内全部工程内容所需的人工、材料、机械、管理、利润、规费、税金、风险及合同约定的其他费用。",
        "",
        "报价文件目录如下：",
        "",
        "1. 已标价工程量清单封面。",
        "2. 投标总价扉页。",
        "3. 总说明。",
        "4. 单项工程投标报价汇总表。",
        "5. 单位工程投标报价汇总表。",
        "6. 分部分项工程和单价措施项目清单与计价表。",
        "7. 总价措施项目清单与计价表。",
        "8. 其他项目清单与计价汇总表。",
        "9. 规费、税金项目计价表。",
        "",
        "报价编制说明：本次投标报价依据招标工程量清单、招标文件、施工图纸、相关规范及企业自有成本测算编制，所有清单数量以招标文件提供为准，综合单价含完成该清单项目所需的全部费用。",
        "",
        "### 5. 投标保证金",
        "",
        "我单位承诺按招标文件规定的金额（________元）、形式（________）、到账时间及有效期提交投标保证金或投标保函；若招标文件要求提供缴纳凭证、电子保函编号或银行回单，将在投标文件相应位置附真实有效资料。",
    ]
    if guarantee_note:
        parts += ["", guarantee_note]
    parts += [
        "",
        "### 6. 各项承诺函",
        "",
        "1. 工期承诺：我单位承诺严格响应招标文件工期要求，合理组织人员、机械、材料和资金投入，确保关键节点按期完成。",
        "2. 质量承诺：我单位承诺工程质量达到招标文件、施工图纸、国家及行业验收规范要求。",
        "3. 安全文明承诺：我单位承诺建立安全生产责任体系，落实文明施工、扬尘治理、临时用电、交通导改和应急管理措施。",
        "4. 环保承诺：我单位承诺严格执行生态环境保护、水土保持、噪声控制、固废处置等要求。",
        "5. 农民工工资承诺：我单位承诺依法建立实名制管理和工资支付保障机制，不拖欠农民工工资。",
        "6. 合规承诺：我单位承诺不转包、不违法分包、不串通投标、不弄虚作假，所有投标资料真实、准确、完整。",
        "",
        "否决投标条款响应：",
        invalid_bid_text,
    ]
    return parts


def _business_bid_from_template(
    requirements: TenderRequirements,
    bid_template: BidTemplate,
    *,
    payment_note: str = "",
    guarantee_note: str = "",
    knowledge_images: list[dict[str, object]] | None = None,
) -> list[str]:
    project_name = _project_title(requirements)
    qualification_text = _format_requirement_items(requirements.qualification_list)
    invalid_bid_text = _format_requirement_items(requirements.invalid_bid_items)
    lines: list[str] = ["【商务标】", "", "## 二、商务标", ""]

    for index, section in enumerate(bid_template.fixed_form_sections, start=1):
        title = section.title
        lines.extend([f"### {index}. {title}", ""])
        section_text = _template_business_section_body(
            title,
            project_name,
            qualification_text,
            invalid_bid_text,
            payment_note,
            guarantee_note,
            knowledge_images,
            requirements,
        )
        lines.extend(section_text)
        if "资格" in title or "证" in title or "业绩" in title:
            lines.extend(
                _knowledge_image_block(
                    knowledge_images,
                    keywords=(
                        "营业执照",
                        "资质",
                        "安全生产",
                        "建造师",
                        "身份证",
                        "建安",
                        "交安",
                        "职称",
                        "社保",
                        "业绩",
                    ),
                )
            )
        lines.append("")

    if not any(
        "报价" in section.title or "清单" in section.title
        for section in bid_template.fixed_form_sections
    ):
        lines.extend(
            [
                "### 报价文件",
                "",
                "本报价文件依据招标文件、工程量清单、施工图纸、补遗澄清文件、现行计价规范及企业施工组织安排编制，投标报价包括完成本项目招标范围内全部工程内容所需的相关费用。",
                "",
            ]
        )

    return lines


def _template_business_section_body(
    title: str,
    project_name: str,
    qualification_text: str,
    invalid_bid_text: str,
    payment_note: str,
    guarantee_note: str,
    knowledge_images: list[dict[str, object]] | None = None,
    requirements: TenderRequirements | None = None,
) -> list[str]:
    if "投标函" in title:
        tenderer = requirements.tenderer_name if requirements else ""
        duration = requirements.planned_duration if requirements else ""
        quality = requirements.quality_standard if requirements else ""
        safety = requirements.safety_target if requirements else ""
        body = [
            f"致：{tenderer or '________'}（招标人名称）",
            f"我方经详细研究{project_name}招标文件及相关资料，决定参加本项目投标，并承诺按招标文件、合同条款、技术标准和工程量清单要求完成全部工作内容。",
            "本次投标总报价为________元（大写：________整），具体金额以已标价工程量清单为准。",
            f"我方承诺计划工期为{duration or '________'}，工程质量达到{quality or '招标文件规定标准'}，安全目标为{safety or '满足招标文件及现行安全生产要求'}，投标有效期、履约担保和合同义务均实质性响应招标文件要求。",
        ]
        if payment_note:
            body.append(payment_note)
        return body
    if "授权" in title or "法定代表人" in title:
        return [
            "法定代表人身份证明及授权委托书按招标文件固定格式填写，载明投标人名称、统一社会信用代码、法定代表人、授权代理人、授权范围和授权期限。",
            "法定代表人姓名（________）、身份证号（________）、授权代理人姓名（________）、身份证号（________）及签章页须使用企业真实资料。",
            "",
            *_knowledge_image_block(knowledge_images, keywords=("身份证", "授权", "法定代表人")),
        ]
    if "联合体" in title:
        return [
            "如本项目允许并采用联合体投标，联合体协议书应明确牵头人、成员单位、职责分工、权利义务和签章要求。",
            "如本项目不采用联合体投标，应按招标文件要求保留相应声明或填写“不适用”。",
        ]
    if "保证金" in title or "保函" in title:
        body = [
            "我单位承诺按招标文件规定的金额（________元）、形式（________）、到账时间及有效期提交投标保证金或投标保函。",
            "若招标文件要求提供缴纳凭证、电子保函编号或银行回单，将在投标文件相应位置附真实有效资料。",
        ]
        if guarantee_note:
            body.append(guarantee_note)
        return body
    if "资格" in title:
        return [
            "资格审查资料按招标文件要求编制，包含企业营业执照、资质证书、安全生产许可证、项目经理资格、技术负责人、专职安全员、类似业绩、财务信誉和信用查询等资料。",
            "招标文件资格要求响应如下：",
            qualification_text,
            "企业资质证书编号（________）、人员证书编号（________）、社保证明、类似业绩项目名称（________）及合同金额（________元）须使用企业真实资料，并附扫描件或复印件。",
            "",
            *_knowledge_image_block(
                knowledge_images,
                keywords=(
                    "营业执照",
                    "资质",
                    "安全生产",
                    "建造师",
                    "身份证",
                    "建安",
                    "交安",
                    "职称",
                    "社保",
                    "业绩",
                ),
            ),
        ]
    if "声明" in title or "承诺" in title:
        return [
            "我单位承诺投标资料真实、准确、完整，不存在串通投标、弄虚作假、行贿、转包或违法分包等情形。",
            "我单位承诺依法履行质量、安全、环保、文明施工、农民工工资支付和廉洁履约义务。",
            "否决投标条款响应：",
            invalid_bid_text,
        ]
    return [
        "本章节按招标文件规定格式编制，企业事实信息、证书编号、金额、人员姓名、日期和签章页均以投标人真实资料为准。",
        "我单位承诺本章节内容与招标文件实质性要求一致，并在最终提交前逐项复核附件、签章和上传格式。",
    ]


def _knowledge_image_block(
    knowledge_images: list[dict[str, object]] | None,
    *,
    keywords: tuple[str, ...] = (),
    limit: int = 6,
) -> list[str]:
    selected = _select_knowledge_images(knowledge_images, keywords, limit)
    if not selected:
        return []
    lines = ["相关证明材料扫描件如下：", ""]
    for image in selected:
        document_id = image.get("document_id")
        if not document_id:
            continue
        caption = str(image.get("caption") or image.get("file_name") or "知识库图片资料")
        lines.append(
            f'{{{{knowledge_image:document_id={int(document_id)} caption="{_escape_marker_caption(caption)}"}}}}'
        )
        lines.append("")
    return lines


def _select_knowledge_images(
    knowledge_images: list[dict[str, object]] | None,
    keywords: tuple[str, ...],
    limit: int,
) -> list[dict[str, object]]:
    if not knowledge_images:
        return []
    if not keywords:
        return knowledge_images[:limit]
    selected: list[dict[str, object]] = []
    for image in knowledge_images:
        text = " ".join(
            str(value)
            for value in (
                image.get("file_name"),
                image.get("caption"),
                image.get("document_type"),
                image.get("specialty"),
                " ".join(str(tag) for tag in image.get("tags", []) or []),
            )
            if value
        )
        if any(keyword in text for keyword in keywords):
            selected.append(image)
            if len(selected) >= limit:
                break
    return selected


def _escape_marker_caption(caption: str) -> str:
    return caption.replace('"', "'").strip()


def generate_bid_section(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
    knowledge_images: list[dict[str, object]] | None = None,
) -> str:
    try:
        return _generate_section_with_llm(
            section_title, requirements, retrieved_chunks, knowledge_images
        )
    except Exception:
        return _generate_section_fallback(section_title, requirements, retrieved_chunks)


def _generate_long_context_with_llm(
    *,
    requirements: TenderRequirements,
    company_name: str,
    document_outline: list[dict[str, object]],
    bid_plan: BidPlan | None,
    template_name: str,
    pricing_strategy: PricingStrategy | None,
    knowledge_chunks: list[dict[str, object]],
    knowledge_images: list[dict[str, object]] | None = None,
    tender_text: str = "",
) -> str:
    settings = get_settings()
    api_key, base_url, model = _llm_client_config(settings)

    timeout_seconds = float(
        getattr(settings, "bid_long_context_timeout_seconds", 180.0)
    )
    max_tokens = int(getattr(settings, "bid_long_context_max_tokens", 12000))
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
    messages = build_long_context_prompt(
        requirements=requirements,
        company_name=company_name,
        document_outline=document_outline,
        bid_plan=bid_plan.model_dump(mode="json") if bid_plan else None,
        template_name=template_name,
        pricing_strategy=pricing_strategy.model_dump(mode="json")
        if pricing_strategy
        else None,
        knowledge_chunks=knowledge_chunks,
        knowledge_images=knowledge_images,
        tender_text=tender_text,
    )

    # 整本标书很容易超过单次输出上限。被截断（finish_reason=length）时先续写
    # 最多 LONG_CONTEXT_MAX_CONTINUATIONS 轮，保住长上下文路径的质量；仍然
    # 截断才抛错，让调用方回退到分章管线，避免静默交付半本标书。
    parts: list[str] = []
    finish_reason = None
    for round_index in range(1 + LONG_CONTEXT_MAX_CONTINUATIONS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.18,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )
        if not response.choices:
            raise GeneratorAgentError("LLM response did not contain choices")
        choice = response.choices[0]
        content = (choice.message.content or "").strip("\n")
        if not content.strip() and not parts:
            raise GeneratorAgentError("LLM response was empty")
        parts.append(content)
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason != "length":
            break
        logger.warning(
            "Long-context output truncated (round %s); requesting continuation",
            round_index + 1,
        )
        messages = [
            *messages,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": "继续输出，从上次中断处继续，不要重复已输出内容，不要重复卷册标记之前的章节。",
            },
        ]

    if finish_reason == "length":
        raise GeneratorAgentError(
            f"长上下文输出在 {1 + LONG_CONTEXT_MAX_CONTINUATIONS} 轮后仍被截断"
            f"（max_tokens={max_tokens}），回退到分章生成。"
        )
    combined = "".join(parts).strip()
    if not combined:
        raise GeneratorAgentError("LLM response was empty")
    return combined


def _llm_client_config(settings) -> tuple[str, str, str]:
    provider = str(getattr(settings, "bid_llm_provider", "auto") or "auto").lower()
    if provider == "deepseek":
        if not _has_real_key(getattr(settings, "deepseek_api_key", "")):
            raise GeneratorAgentError(
                "DEEPSEEK_API_KEY is required when BID_LLM_PROVIDER=deepseek"
            )
        return (
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    if provider == "openrouter":
        if not _has_real_key(getattr(settings, "openrouter_api_key", "")):
            raise GeneratorAgentError(
                "OPENROUTER_API_KEY is required when BID_LLM_PROVIDER=openrouter"
            )
        return (
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
        )
    if _has_real_key(getattr(settings, "openrouter_api_key", "")):
        api_key = settings.openrouter_api_key
        base_url = settings.openrouter_base_url
        model = settings.openrouter_model
    elif _has_real_key(getattr(settings, "deepseek_api_key", "")):
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model = settings.deepseek_model
    else:
        raise GeneratorAgentError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")
    return api_key, base_url, model


def _generate_section_with_llm(
    section_title: str,
    requirements: TenderRequirements,
    retrieved_chunks: list[str],
    knowledge_images: list[dict[str, object]] | None = None,
) -> str:
    settings = get_settings()
    api_key, base_url, model = _llm_client_config(settings)

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=25.0)
    response = client.chat.completions.create(
        model=model,
        messages=build_section_prompt(
            section_title, requirements, retrieved_chunks, knowledge_images
        ),
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


def _long_context_chunks(
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
) -> list[dict[str, object]]:
    packed: list[dict[str, object]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for section_title, chunks in retrieved_chunks_by_section.items():
        for chunk in chunks:
            content = _chunk_content(chunk).strip()
            if not content or _is_structured_evidence_chunk(chunk, content):
                continue
            chunk_id = _chunk_id(chunk)
            key = (section_title, chunk_id, content[:160])
            if key in seen:
                continue
            seen.add(key)
            metadata = chunk.metadata if isinstance(chunk, RetrievalResult) else {}
            packed.append(
                {
                    "section_title": section_title,
                    "chunk_id": chunk_id,
                    "document_id": _int_or_none(getattr(chunk, "document_id", None))
                    if not isinstance(chunk, str)
                    else None,
                    "title": metadata.get("file_name", "") if metadata else "",
                    "content": content,
                    "metadata": metadata or {},
                }
            )
    return packed[:24]


def _filter_knowledge_images_by_plan(
    knowledge_images: list[dict[str, object]] | None,
    bid_plan: BidPlan | dict | None,
) -> list[dict[str, object]] | None:
    if not knowledge_images:
        return knowledge_images
    plan = _coerce_bid_plan(bid_plan)
    if not plan:
        return knowledge_images
    planned_ids = {
        int(document_id)
        for section in plan.sections
        for document_id in section.image_document_ids
        if document_id is not None
    }
    if not planned_ids:
        return knowledge_images
    return [
        image
        for image in knowledge_images
        if _int_or_none(image.get("document_id")) in planned_ids
    ]


def _filter_chunks_for_bid_plan(
    chunks: list[RetrievalResult | str],
    bid_plan: BidPlan | dict | None,
    section_title: str,
) -> list[RetrievalResult | str]:
    plan = _coerce_bid_plan(bid_plan)
    if not plan:
        return chunks
    section_plan = plan.section_for_title(section_title)
    if not section_plan or not section_plan.evidence_chunk_ids:
        return chunks
    allowed_ids = {int(chunk_id) for chunk_id in section_plan.evidence_chunk_ids}
    filtered = [
        chunk
        for chunk in chunks
        if isinstance(chunk, str) or _chunk_id(chunk) in allowed_ids
    ]
    return filtered


def _coerce_bid_plan(bid_plan: BidPlan | dict | None) -> BidPlan | None:
    if bid_plan is None:
        return None
    if isinstance(bid_plan, BidPlan):
        return bid_plan
    try:
        return BidPlan.model_validate(bid_plan)
    except Exception:
        return None


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

| 控制项目 | 主要措施 | 责任岗位 | 形成资料 |
| --- | --- | --- | --- |
| 技术交底 | 分部分项工程开工前完成书面交底，明确工艺、质量、安全和环保要求 | 技术负责人、施工员 | 技术交底记录 |
| 过程检查 | 对关键工序实行旁站、巡检和隐蔽验收，发现偏差及时整改闭合 | 质量员、安全员 | 检查记录、整改闭合单 |
| 资料归档 | 施工记录、试验检测、验收资料与现场进度同步形成 | 资料员、专业工程师 | 施工资料台账 |

#### 三、风险与合规控制
针对招标文件列明的否决投标、重大偏差和实质性响应要求，我单位将在投标文件编制、施工准备、过程实施和交验收尾各阶段逐项复核，确保工期、质量、安全、资质、人员、设备、保证金及其他承诺均实质性响应招标文件。
"""


def _bid_text_chunks(chunks: list[RetrievalResult | str]) -> list[str]:
    return [
        content
        for chunk in chunks
        if (content := _chunk_content(chunk).strip())
        and not _is_structured_evidence_chunk(chunk, content)
    ]


def _chunk_id(chunk: RetrievalResult | str) -> int | None:
    if isinstance(chunk, str):
        return None
    return _int_or_none(chunk.chunk_id)


def _int_or_none(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_structured_evidence_chunk(chunk: RetrievalResult | str, content: str) -> bool:
    if content.startswith("资料名称："):
        return True
    if isinstance(chunk, RetrievalResult):
        metadata = chunk.metadata or {}
        if metadata.get("ingestion_mode") in {"structured_evidence", "evidence_only"}:
            return True
        if metadata.get("indexing_status") in {"structured_evidence", "evidence_only"}:
            return True
        file_type = str(metadata.get("file_type") or "").lower()
        if file_type in {"jpg", "jpeg", "png", "gif", "webp"}:
            return True
    return False


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


def _section_title_for_item(
    item: RequirementItem,
    candidate_titles: list[str] | None = None,
) -> str:
    combined = f"{item.title} {item.description}"
    candidate_titles = candidate_titles or BID_TEMPLATE_SECTION_TITLES

    best_title = ""
    best_score = 0
    for section_title in candidate_titles:
        keywords = SECTION_KEYWORDS.get(section_title, ())
        score = sum(1 for keyword in keywords if keyword in combined)
        if item.title and item.title in section_title:
            score += 3
        for phrase in _meaningful_phrases(item.description):
            if phrase in section_title:
                score += 2
        if not score:
            title_tokens = [
                token
                for token in section_title.replace("、", " ").replace("与", " ").split()
                if len(token) >= 2
            ]
            score = sum(1 for token in title_tokens if token in combined)
        if score > best_score:
            best_title = section_title
            best_score = score

    if best_title:
        return best_title

    for section_title, keywords in SECTION_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return (
                section_title
                if section_title in candidate_titles
                else candidate_titles[0]
            )
    return candidate_titles[0] if candidate_titles else "第二章、主要工程项目的施工方案、方法与技术措施"


def _meaningful_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for raw in text.replace("，", " ").replace("、", " ").replace("与", " ").split():
        cleaned = raw.strip(" ：:；;,.。()（）0123456789分")
        if len(cleaned) >= 2:
            phrases.append(cleaned)
    return phrases


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


def _format_requirement_items(items: list[RequirementItem]) -> str:
    if not items:
        return "- 招标文件未解析出明确条款，投标文件按招标文件全部实质性要求响应。"
    lines = []
    for item in items:
        title = item.title.strip() if item.title else "招标要求"
        description = item.description.strip()
        if description:
            lines.append(f"- {title}：{description}")
    return "\n".join(lines) if lines else "- 招标文件未解析出明确条款。"


def _chunk_content(chunk: RetrievalResult | str) -> str:
    if isinstance(chunk, str):
        return chunk
    return chunk.content


def _technical_titles_from_template(
    bid_template: BidTemplate | None,
) -> list[str]:
    if not bid_template:
        return []
    titles = [
        section.title
        for section in bid_template.construction_design_sections
        if section.level == 1 and section.title
    ]
    if titles:
        return titles
    return [
        section.title
        for section in bid_template.main_sections
        if section.section_type == "construction_design" and section.title
    ]


def _appendix_fallback(bid_template: BidTemplate) -> list[str]:
    lines = ["## 附图附表", ""]
    for section in bid_template.appendix_sections:
        lines.extend(
            [
                f"### {section.title}",
                "",
                "本附表依据招标文件、施工图纸、工程量清单及施工组织设计编制，作为施工进度安排、资源投入、临时设施布置和现场组织管理的组成部分。",
                "",
                "| 序号 | 附表内容 | 编制依据 | 响应说明 |",
                "| --- | --- | --- | --- |",
                "| 1 | 施工计划、资源投入或现场布置数据 | 招标文件、施工图纸、施工组织设计 | 满足招标文件工期、质量、安全和现场管理要求 |",
                "| 2 | 关键节点、劳动力、机械设备及临时设施 | 工期要求、工程量清单、资源配置计划 | 与施工组织设计、报价文件及合同履约安排保持一致 |",
                "",
                "我单位承诺本附表所列时间节点、工程量、劳动力、机械设备、临时用地及外供电力等内容与施工组织设计、报价文件和招标文件要求保持一致，并在项目实施过程中按合同约定和现场实际组织落实。",
                "",
            ]
        )
    return lines
