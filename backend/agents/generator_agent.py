from __future__ import annotations

import re
from pathlib import Path

from core.config import get_settings
from schemas.bid import BidDocumentOutlineSection, BidSectionOutline
from schemas.bid_template import BidTemplate
from schemas.tender import RequirementItem, TenderRequirements


BACKEND_DIR = Path(__file__).resolve().parents[1]

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

    return outlines if template_titles else outlines[:MAX_OUTLINE_SECTIONS]


def build_bid_document_outline(
    requirements: TenderRequirements,
    bid_template: BidTemplate | None = None,
) -> list[BidDocumentOutlineSection]:
    technical_outline = build_bid_outline(requirements, bid_template)
    technical_children = [
        BidDocumentOutlineSection(
            title=section.title,
            volume="技术标",
            section_type="construction_design",
            required=section.required,
            source_item=section.source_item,
            focus_points=section.focus_points,
            manual_image_slots=section.manual_image_slots,
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


def _document_volume_for_section(title: str, section_type: str) -> str:
    combined = f"{title} {section_type}"
    if any(keyword in combined for keyword in ("报价", "清单", "投标总价", "price")):
        return "报价/经济标"
    if section_type == "construction_design" or "施工组织设计" in title:
        return "技术标"
    if section_type == "appendix":
        return "技术标"
    return "商务/资格标"


def _section_title_for_item(
    item: RequirementItem,
    candidate_titles: list[str] | None = None,
) -> str:
    candidate_titles = candidate_titles or BID_TEMPLATE_SECTION_TITLES
    text = f"{item.title} {item.description}"
    for title in candidate_titles:
        keywords = SECTION_KEYWORDS.get(title, ())
        if any(keyword in text for keyword in keywords):
            return title
    phrases = _meaningful_phrases(text)
    for phrase in phrases:
        for title in candidate_titles:
            if phrase and phrase in title:
                return title
    return candidate_titles[0]


def _meaningful_phrases(text: str) -> list[str]:
    return [
        token
        for token in re.split(r"[\s，。；、/（）()]+", text)
        if len(token) >= 2
    ]


def _append_focus(
    outlines: list[BidSectionOutline],
    title: str,
    focus: str,
) -> None:
    for outline in outlines:
        if outline.title == title:
            if focus and focus not in outline.focus_points:
                outline.focus_points.append(focus)
            return


def _technical_titles_from_template(bid_template: BidTemplate | None) -> list[str]:
    if not bid_template:
        return []
    titles = [
        section.title
        for section in bid_template.construction_design_sections
        if section.title
    ]
    if titles:
        return titles
    titles = [
        section.title
        for section in bid_template.main_sections
        if section.section_type == "construction_design" and section.title
    ]
    return titles
