from __future__ import annotations

from typing import Any

from schemas.bid import BidDocumentOutlineSection
from schemas.bid_plan import BidPlan, BidPlanSection
from schemas.evidence import EvidenceItem, EvidencePack
from schemas.template_profile import TemplateProfile, TemplateSlot
from schemas.tender import TenderRequirements


QUALIFICATION_KEYWORDS = (
    "资格",
    "证",
    "法人",
    "授权",
    "项目经理",
    "技术负责人",
    "安全员",
    "人员",
    "业绩",
)
TECHNICAL_KEYWORDS = (
    "施工",
    "技术",
    "质量",
    "安全",
    "工期",
    "进度",
    "环保",
    "文明",
    "应急",
    "保通",
    "组织设计",
)
PRICING_KEYWORDS = ("报价", "清单", "投标总价", "经济标", "计价")
TABLE_KEYWORDS = ("表", "附表", "计划", "清单", "汇总", "机构", "配置")


def build_bid_plan(
    requirements: TenderRequirements,
    *,
    template_profile: TemplateProfile | None = None,
    evidence_pack: EvidencePack | None = None,
    document_outline: list[BidDocumentOutlineSection | dict[str, Any]] | None = None,
) -> BidPlan:
    evidence_pack = evidence_pack or EvidencePack()
    sections = _sections_from_profile_or_outline(template_profile, document_outline)
    if not sections:
        sections = _fallback_sections()

    plan_sections = [
        _build_section_plan(
            section,
            requirements,
            evidence_pack,
            template_profile,
        )
        for section in sections
    ]
    notes = [
        "BidPlan 是生成阶段唯一的结构控制层：模板负责章节顺序，知识库只提供证据素材。",
        *evidence_pack.notes,
    ]
    if template_profile:
        notes.append(f"已应用模板画像：{template_profile.template_name}")
    return BidPlan(
        template_name=template_profile.template_name if template_profile else "",
        sections=plan_sections,
        evidence_summary=evidence_pack.counts(),
        notes=notes,
    )


def _build_section_plan(
    seed: BidPlanSection,
    requirements: TenderRequirements,
    evidence_pack: EvidencePack,
    template_profile: TemplateProfile | None,
) -> BidPlanSection:
    title_text = seed.title
    chunk_ids = _chunk_ids_for_section(title_text, evidence_pack)
    image_ids = _image_ids_for_section(title_text, evidence_pack, template_profile)
    requirement_refs = _requirement_refs_for_section(title_text, requirements)
    table_required = seed.table_required or _section_needs_table(
        title_text, template_profile
    )
    return seed.model_copy(
        update={
            "requirement_refs": requirement_refs,
            "evidence_chunk_ids": chunk_ids,
            "image_document_ids": image_ids,
            "table_required": table_required,
            "blank_fields": list(seed.blank_fields or _blank_fields(template_profile)),
            "tone_rules": list(seed.tone_rules or _tone_rules(template_profile)),
            "forbidden_phrases": list(
                seed.forbidden_phrases or _forbidden_phrases(template_profile)
            ),
        }
    )


def _sections_from_profile_or_outline(
    template_profile: TemplateProfile | None,
    document_outline: list[BidDocumentOutlineSection | dict[str, Any]] | None,
) -> list[BidPlanSection]:
    if template_profile and template_profile.section_order:
        return [
            BidPlanSection(
                title=title,
                volume=_volume_for_profile_title(template_profile, title),
                section_type=_section_type_for_title(title),
                table_required=_slot_exists(template_profile.table_slots, title),
            )
            for title in template_profile.section_order
        ]

    outline_sections = _flatten_outline(document_outline or [])
    if outline_sections:
        return outline_sections

    if template_profile and template_profile.volumes:
        sections: list[BidPlanSection] = []
        for volume in template_profile.volumes:
            for title in volume.section_titles:
                sections.append(
                    BidPlanSection(
                        title=title,
                        volume=volume.name,
                        section_type=_section_type_for_title(title),
                        table_required=_slot_exists(
                            template_profile.table_slots, title
                        ),
                    )
                )
        return sections

    return []


def _flatten_outline(
    document_outline: list[BidDocumentOutlineSection | dict[str, Any]],
) -> list[BidPlanSection]:
    sections: list[BidPlanSection] = []

    def visit(raw: BidDocumentOutlineSection | dict[str, Any], parent_volume: str = ""):
        section = (
            raw
            if isinstance(raw, BidDocumentOutlineSection)
            else BidDocumentOutlineSection.model_validate(raw)
        )
        volume = section.volume or parent_volume or "技术标"
        sections.append(
            BidPlanSection(
                title=section.title,
                volume=volume,
                section_type=section.section_type,
                required=section.required,
                table_required=_contains_any(section.title, TABLE_KEYWORDS),
            )
        )
        for child in section.children:
            visit(child, volume)

    for raw_section in document_outline:
        visit(raw_section)
    return sections


def _fallback_sections() -> list[BidPlanSection]:
    return [
        BidPlanSection(title="商务文件", volume="商务/资格标", section_type="business"),
        BidPlanSection(title="施工组织设计", volume="技术标", section_type="technical"),
        BidPlanSection(title="报价文件", volume="报价/经济标", section_type="pricing"),
    ]


def _chunk_ids_for_section(title: str, evidence_pack: EvidencePack) -> list[int]:
    if _contains_any(title, PRICING_KEYWORDS):
        items = evidence_pack.pricing_attachments + evidence_pack.table_attachments
    elif _contains_any(title, QUALIFICATION_KEYWORDS):
        items = [
            *evidence_pack.company_certificates,
            *evidence_pack.person_certificates,
            *evidence_pack.performance_projects,
        ]
    elif _contains_any(title, TECHNICAL_KEYWORDS):
        items = evidence_pack.technical_schemes + evidence_pack.table_attachments
    else:
        items = evidence_pack.other_references + evidence_pack.technical_schemes
    return _unique_ints(item.chunk_id for item in items if item.chunk_id is not None)


def _image_ids_for_section(
    title: str,
    evidence_pack: EvidencePack,
    template_profile: TemplateProfile | None,
) -> list[int]:
    slot_keywords = _slot_keywords(
        template_profile.image_slots if template_profile else [], title
    )
    if _contains_any(title, QUALIFICATION_KEYWORDS):
        keywords = (*QUALIFICATION_KEYWORDS, *slot_keywords)
    elif _contains_any(title, TECHNICAL_KEYWORDS):
        keywords = ("施工平面图", "现场", "布置", *slot_keywords)
    else:
        keywords = slot_keywords
    if not keywords:
        return []
    matching = [
        item.document_id
        for item in evidence_pack.image_evidence
        if item.document_id is not None and _item_matches_keywords(item, keywords)
    ]
    return _unique_ints(matching)


def _requirement_refs_for_section(
    title: str,
    requirements: TenderRequirements,
) -> list[str]:
    refs: list[str] = []
    source_items = [
        *requirements.qualification_list,
        *requirements.technical_score_items,
        *requirements.invalid_bid_items,
    ]
    for item in source_items:
        text = f"{item.title} {item.description}"
        if _section_matches_requirement(title, text):
            refs.append(item.description or item.title)
    return refs[:8]


def _section_matches_requirement(title: str, requirement_text: str) -> bool:
    if not requirement_text:
        return False
    if any(
        keyword in title and keyword in requirement_text
        for keyword in QUALIFICATION_KEYWORDS
    ):
        return True
    if any(
        keyword in title and keyword in requirement_text
        for keyword in TECHNICAL_KEYWORDS
    ):
        return True
    if any(
        keyword in title and keyword in requirement_text for keyword in PRICING_KEYWORDS
    ):
        return True
    return False


def _section_needs_table(
    title: str,
    template_profile: TemplateProfile | None,
) -> bool:
    return _contains_any(title, TABLE_KEYWORDS) or bool(
        template_profile and _slot_exists(template_profile.table_slots, title)
    )


def _volume_for_profile_title(profile: TemplateProfile, title: str) -> str:
    for volume in profile.volumes:
        if title in volume.section_titles:
            return volume.name
    if _contains_any(title, PRICING_KEYWORDS):
        return "报价/经济标"
    if _contains_any(title, QUALIFICATION_KEYWORDS):
        return "商务/资格标"
    return "技术标"


def _section_type_for_title(title: str) -> str:
    if _contains_any(title, PRICING_KEYWORDS):
        return "pricing"
    if _contains_any(title, QUALIFICATION_KEYWORDS):
        return "business"
    if _contains_any(title, TECHNICAL_KEYWORDS):
        return "technical"
    return "content"


def _slot_exists(slots: list[TemplateSlot], title: str) -> bool:
    return any(_titles_match(slot.section_title, title) for slot in slots)


def _slot_keywords(slots: list[TemplateSlot], title: str) -> tuple[str, ...]:
    keywords: list[str] = []
    for slot in slots:
        if not _titles_match(slot.section_title, title):
            continue
        keywords.extend(slot.evidence_categories)
        keywords.extend(_meaningful_tokens(slot.description))
        keywords.extend(_meaningful_tokens(slot.section_title))
    return tuple(dict.fromkeys(keyword for keyword in keywords if keyword))


def _item_matches_keywords(item: EvidenceItem, keywords: tuple[str, ...]) -> bool:
    text = item.search_text()
    return _contains_any(text, keywords)


def _blank_fields(template_profile: TemplateProfile | None) -> list[str]:
    return template_profile.blank_fields if template_profile else []


def _tone_rules(template_profile: TemplateProfile | None) -> list[str]:
    return template_profile.tone_rules if template_profile else []


def _forbidden_phrases(template_profile: TemplateProfile | None) -> list[str]:
    return template_profile.forbidden_phrases if template_profile else []


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    compact = text.replace(" ", "").replace("　", "")
    return any(keyword and keyword in compact for keyword in keywords)


def _titles_match(left: str, right: str) -> bool:
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    return bool(left_norm and right_norm) and (
        left_norm == right_norm or left_norm in right_norm or right_norm in left_norm
    )


def _normalize_title(title: str) -> str:
    return (
        title.replace(" ", "")
        .replace("　", "")
        .replace("#", "")
        .replace("、", "")
        .replace("，", "")
        .replace(",", "")
        .strip()
    )


def _meaningful_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in (
        text.replace("，", " ")
        .replace("、", " ")
        .replace("：", " ")
        .replace(":", " ")
        .split()
    ):
        cleaned = token.strip("。；;,.()（）[]【】")
        if len(cleaned) >= 2:
            tokens.append(cleaned)
    return tokens


def _unique_ints(values) -> list[int]:
    return sorted({int(value) for value in values if value is not None})
