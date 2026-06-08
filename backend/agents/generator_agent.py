from __future__ import annotations

import re
from pathlib import Path

from openai import OpenAI

from agents.parser_agent import _has_real_key, _is_placeholder_project_name
from core.config import get_settings
from prompts.generator_prompt import build_document_prompt, build_section_prompt
from rag.retriever import RetrievalResult
from schemas.bid import BidDocumentOutlineSection, BidSectionOutline
from schemas.bid_template import BidTemplate
from schemas.strategy import PricingStrategy
from schemas.tender import RequirementItem, TenderRequirements


class GeneratorAgentError(RuntimeError):
    pass


BACKEND_DIR = Path(__file__).resolve().parents[1]


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
                focus_points=["具体报价金额和工程量清单必须由造价人员或清单数据填报。"],
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
                focus_points=["系统不自动编造投标总价、综合单价或清单合价。"],
            )
        )
    return document_outline


def generate_bid_document(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    bid_template: BidTemplate | None = None,
    pricing_strategy: PricingStrategy | None = None,
) -> str:
    bid_template = bid_template or load_bid_template()
    outline = build_bid_outline(requirements, bid_template)
    settings = get_settings()
    use_local_section_fallback = False
    if settings.enable_llm_generation:
        try:
            markdown = _generate_document_with_llm(
                requirements,
                outline,
                retrieved_chunks_by_section,
                settings.company_name,
                bid_template,
                pricing_strategy,
            )
            return sanitize_bid_markdown(
                _ensure_document_header(markdown, requirements, settings.company_name)
            )
        except Exception:
            use_local_section_fallback = True
    else:
        use_local_section_fallback = True

    if bid_template and bid_template.main_sections:
        return _generate_template_ordered_document_fallback(
            requirements,
            retrieved_chunks_by_section,
            bid_template,
            pricing_strategy,
            use_local_section_fallback,
        )

    parts = _document_preface(requirements, settings.company_name)
    parts.extend(["", "【技术标】", "", "## 一、技术标", "", "### 技术标目录", ""])
    for section in outline:
        parts.append(f"- {section.title}")
    if bid_template and bid_template.appendix_sections:
        parts.append("")
        parts.append("附表目录：")
        for section in bid_template.appendix_sections:
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
        parts.append(section_markdown)
        parts.append("")
    if bid_template and bid_template.appendix_sections:
        parts.extend(_appendix_fallback(bid_template))
        parts.append("")
    parts.extend(_business_bid_fallback(requirements, pricing_strategy, bid_template))
    return sanitize_bid_markdown("\n".join(parts).strip() + "\n")


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
    title = f"# {_project_title(requirements)} 投标文件"
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

    text = "\n".join(lines).strip()
    has_business_block = "【商务标】" in text or "## 一、商务标" in text or "## 二、商务标" in text
    has_technical_block = "【技术标】" in text or "## 一、技术标" in text or "## 二、技术标" in text
    if not has_business_block:
        fallback_business = _business_bid_fallback(requirements)
        technical_body = "\n".join(lines[1:]).strip()
        lines = [
            *_document_preface(requirements, company_name),
            "【技术标】",
            "",
            "## 一、技术标",
            "",
            technical_body,
            "",
            *fallback_business,
        ]
    elif not has_technical_block:
        lines.insert(3, "")
        lines.insert(4, "【技术标】")
        lines.insert(5, "")
        lines.insert(6, "## 一、技术标")

    return "\n".join(lines).strip() + "\n"


def _document_preface(
    requirements: TenderRequirements,
    company_name: str,
) -> list[str]:
    project_name = _project_title(requirements)
    return [
        f"# {project_name} 投标文件",
        "",
        f"投标人：{company_name}",
        "",
        "## 投标文件响应总说明",
        "",
        f"我单位已认真研究{project_name}招标文件、补遗澄清文件及相关技术资料，充分理解招标范围、资格条件、评审办法、合同条款、工期质量安全要求及否决投标条款。本投标文件按照招标文件和模板目录顺序编制，做到资格、商务、技术、报价及附表资料逐项响应，并对所提交资料的真实性负责。",
        "",
    ]


def _generate_template_ordered_document_fallback(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    bid_template: BidTemplate,
    pricing_strategy: PricingStrategy | None,
    use_local_section_fallback: bool,
) -> str:
    settings = get_settings()
    outline = build_bid_outline(requirements, bid_template)
    parts = _document_preface(requirements, settings.company_name)
    parts.extend(["## 投标文件目录", ""])
    for section in build_bid_document_outline(requirements, bid_template):
        parts.append(f"- [{section.volume}] {section.title}")
        for child in section.children[:12]:
            parts.append(f"  - {child.title}")
    parts.append("")

    emitted_appendices = False
    emitted_price = False
    for section in bid_template.main_sections:
        if section.section_type == "construction_design":
            parts.extend(
                _technical_volume_from_outline(
                    requirements,
                    outline,
                    retrieved_chunks_by_section,
                    use_local_section_fallback,
                )
            )
            if bid_template.appendix_sections and not emitted_appendices:
                parts.extend(_appendix_fallback(bid_template))
                emitted_appendices = True
            continue

        if (
            _document_volume_for_section(section.title, section.section_type)
            == "报价/经济标"
        ):
            parts.extend(_price_bid_fallback(pricing_strategy))
            emitted_price = True
            continue

        parts.extend(
            _business_section_from_template(requirements, section, pricing_strategy)
        )

    if bid_template.appendix_sections and not emitted_appendices:
        parts.extend(_appendix_fallback(bid_template))
    if not emitted_price:
        parts.extend(_price_bid_fallback(pricing_strategy, missing_template=True))

    return sanitize_bid_markdown("\n".join(parts).strip() + "\n")


def _technical_volume_from_outline(
    requirements: TenderRequirements,
    outline: list[BidSectionOutline],
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    use_local_section_fallback: bool,
) -> list[str]:
    parts = ["## 五、施工组织设计", "", "### 施工组织设计目录", ""]
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
        parts.extend([section_markdown, ""])
    return parts


def _business_section_from_template(
    requirements: TenderRequirements,
    section,
    pricing_strategy: PricingStrategy | None,
) -> list[str]:
    payment_note, guarantee_note = _pricing_context_notes(pricing_strategy)
    body = _template_business_section_body(
        section.title,
        _project_title(requirements),
        _format_requirement_items(requirements.qualification_list),
        _format_requirement_items(requirements.invalid_bid_items),
        payment_note,
        guarantee_note,
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
        "本部分仅生成报价文件目录和编制说明，具体工程量、综合单价、合价、措施项目费、规费、税金及投标总价须由造价人员依据招标工程量清单、图纸、补遗文件和企业成本测算填报，系统不自动生成任何报价数值。",
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
        )

    parts: list[str] = [
        "【商务标】",
        "",
        "## 二、商务标",
        "",
        "### 1. 投标函及投标函附录",
        "",
        "致：________（招标人名称）",
        "",
        f"1. 我方经详细研究{project_name}招标文件及相关资料，决定参加本项目投标，并承诺按招标文件、合同条款、技术标准和工程量清单要求完成全部工作内容。",
        "2. 本次投标总报价为________元（大写：________整），具体金额以已标价工程量清单为准，由造价人员核定后填写。",
        "3. 我方承诺的工期严格响应招标文件要求（________日历天）；工程质量标准达到招标文件规定的合格及以上等级。",
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
        "### 4. 报价文件",
        "",
        "本部分仅生成报价文件目录和编制说明，具体工程量、综合单价、合价、措施项目费、规费、税金及投标总价须由造价人员依据招标工程量清单、图纸、补遗文件和企业成本测算填报，系统不自动生成任何报价数值。",
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
        "报价编制说明：本次投标报价依据招标工程量清单、招标文件、施工图纸、相关规范及企业自有成本测算编制，所有清单数量以招标文件提供为准，综合单价含完成该清单项目所需的全部费用。具体报价金额、工程量及单价由造价人员核定后填写。",
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
        )
        lines.extend(section_text)
        lines.append("")

    if not any(
        "报价" in section.title or "清单" in section.title
        for section in bid_template.fixed_form_sections
    ):
        lines.extend(
            [
                "### 报价文件",
                "",
                "本部分仅生成报价文件目录和编制说明，具体工程量、综合单价、合价、措施项目费、规费、税金及投标总价须由造价人员依据招标工程量清单、图纸、补遗文件和企业成本测算填报，系统不自动生成任何报价数值。",
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
) -> list[str]:
    if "投标函" in title:
        body = [
            f"我方经详细研究{project_name}招标文件及相关资料，决定参加本项目投标，并承诺按招标文件、合同条款、技术标准和工程量清单要求完成全部工作内容。",
            "本次投标总报价为________元（大写：________整），具体金额以已标价工程量清单为准，由造价人员核定后填写。",
            "我方承诺工期、质量、安全、投标有效期、履约担保和合同义务均实质性响应招标文件要求。",
        ]
        if payment_note:
            body.append(payment_note)
        return body
    if "授权" in title or "法定代表人" in title:
        return [
            "法定代表人身份证明及授权委托书按招标文件固定格式填写，载明投标人名称、统一社会信用代码、法定代表人、授权代理人、授权范围和授权期限。",
            "法定代表人姓名（________）、身份证号（________）、授权代理人姓名（________）、身份证号（________）及签章页须使用企业真实资料。",
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
        ]
    if "声明" in title or "承诺" in title:
        return [
            "我单位承诺投标资料真实、准确、完整，不存在串通投标、弄虚作假、行贿、转包或违法分包等情形。",
            "我单位承诺依法履行质量、安全、环保、文明施工、农民工工资支付和廉洁履约义务。",
            "否决投标条款响应：",
            invalid_bid_text,
        ]
    return [
        "本章节按真实投标模板固定表单保留，具体企业事实信息、证书编号、金额、人员姓名、日期和签章页由投标人依据真实资料填写。",
        "我单位承诺本章节内容与招标文件实质性要求一致，并在最终提交前逐项复核附件、签章和上传格式。",
    ]


def _generate_document_with_llm(
    requirements: TenderRequirements,
    outline: list[BidSectionOutline],
    retrieved_chunks_by_section: dict[str, list[RetrievalResult | str]],
    company_name: str,
    bid_template: BidTemplate | None = None,
    pricing_strategy: PricingStrategy | None = None,
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
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
    response = client.chat.completions.create(
        model=model,
        messages=build_document_prompt(
            requirements=requirements,
            outline_titles=[section.title for section in outline],
            retrieved_chunks=chunks,
            company_name=company_name,
            bid_template=bid_template,
            pricing_strategy=pricing_strategy,
        ),
        temperature=0.2,
        max_tokens=9000,
        timeout=60.0,
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

本章响应度自查：完全满足
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
                "本附表按招标文件和真实投标模板要求设置，用于支撑施工组织设计、进度安排、资源配置和现场布置等内容。",
                "",
                "⚠️人工确认点：【待补充】本表涉及的时间节点、工程量、劳动力、机械设备、临时用地、外供电力等数据须由项目技术负责人和造价人员依据真实施工组织安排填写。",
                "",
                "本章响应度自查：完全满足",
                "",
            ]
        )
    return lines
