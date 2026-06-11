from __future__ import annotations

from schemas.bid_template import BidTemplate
from schemas.template_profile import (
    TemplateProfile,
    TemplateSlot,
    TemplateVolumeProfile,
)


DEFAULT_FORBIDDEN_PHRASES = [
    "系统不自动",
    "本部分仅生成",
    "真实投标模板要求",
    "由用户填写",
    "由造价人员填写",
    "由项目技术负责人复核填写",
    "AI",
    "RAG",
    "prompt",
    "metadata",
    "资料名称：",
    "图片用途：",
]

DEFAULT_TONE_RULES = [
    "使用正式投标文件语气，以投标人承诺、响应和编制依据表述，不暴露系统生成过程。",
    "章节结构以案例标书模板为准，不在 prompt 中另造目录。",
    "企业事实、人员证书、业绩、金额和日期必须来自用户确认资料；缺失时保留下划线空白。",
    "报价文件只写正式报价编制说明和清单目录，不编造投标总价、综合单价或清单合价。",
    "知识库资料只作为证据、措辞和图片来源，不把 metadata 摘要写入正文。",
]

DEFAULT_BLANK_FIELDS = [
    "投标总报价",
    "大写金额",
    "工期",
    "质量标准",
    "项目经理姓名",
    "证书编号",
    "身份证号",
    "投标保证金金额",
    "签章日期",
]


def build_template_profile(
    bid_template: BidTemplate,
    *,
    project_type: str | None = None,
    specialty: str | None = None,
) -> TemplateProfile:
    """Summarise a parsed case bid into generation rules.

    This first version is deterministic on purpose. It produces stable JSON that
    can later be enhanced by an LLM reviewer without making the generator depend
    on a free-form prompt as the source of structure.
    """
    section_order = [section.title for section in bid_template.main_sections]
    fixed_forms = [section.title for section in bid_template.fixed_form_sections]
    appendix_tables = [section.title for section in bid_template.appendix_sections]
    volumes = _infer_volumes(bid_template)
    return TemplateProfile(
        template_name=bid_template.template_name,
        source_file=bid_template.source_file,
        project_type=project_type,
        specialty=specialty,
        envelope_type=bid_template.envelope_type,
        document_type=bid_template.document_type,
        volumes=volumes,
        section_order=section_order,
        fixed_forms=fixed_forms,
        appendix_tables=appendix_tables,
        image_slots=_infer_image_slots(bid_template),
        table_slots=_infer_table_slots(bid_template),
        blank_fields=DEFAULT_BLANK_FIELDS,
        tone_rules=DEFAULT_TONE_RULES,
        forbidden_phrases=DEFAULT_FORBIDDEN_PHRASES,
        notes=[
            "TemplateProfile is the generation contract derived from the case bid.",
            "BidTemplate stores extracted structure; TemplateProfile stores how generation should use it.",
        ],
    )


def _infer_volumes(bid_template: BidTemplate) -> list[TemplateVolumeProfile]:
    commercial_titles: list[str] = []
    technical_titles: list[str] = []
    pricing_titles: list[str] = []
    for section in bid_template.main_sections:
        volume = _volume_for_section(section.title, section.section_type)
        if volume == "商务文件":
            commercial_titles.append(section.title)
        elif volume == "技术文件":
            technical_titles.append(section.title)
        else:
            pricing_titles.append(section.title)
    if bid_template.construction_design_sections:
        technical_titles.extend(
            section.title
            for section in bid_template.construction_design_sections
            if section.level == 1
        )
    if bid_template.appendix_sections:
        technical_titles.append("附图附表")
    volumes = [
        TemplateVolumeProfile(
            name="商务文件",
            role="qualification_and_commercial",
            section_titles=_dedupe(commercial_titles),
        ),
        TemplateVolumeProfile(
            name="技术文件",
            role="technical_solution",
            section_titles=_dedupe(technical_titles),
        ),
    ]
    if pricing_titles or "第二信封" in bid_template.envelope_type:
        volumes.append(
            TemplateVolumeProfile(
                name="报价文件",
                role="pricing",
                section_titles=_dedupe(pricing_titles) or ["报价文件"],
            )
        )
    else:
        volumes.append(
            TemplateVolumeProfile(
                name="报价文件",
                role="pricing_gap",
                section_titles=["报价文件（如招标文件要求）"],
            )
        )
    return volumes


def _infer_image_slots(bid_template: BidTemplate) -> list[TemplateSlot]:
    slots: list[TemplateSlot] = []
    for section in bid_template.main_sections + bid_template.fixed_form_sections:
        title = section.title
        if any(keyword in title for keyword in ("资格", "证", "项目管理机构", "业绩")):
            slots.append(
                TemplateSlot(
                    section_title=title,
                    slot_type="knowledge_image",
                    description="插入营业执照、资质证书、安全生产许可证、人员证书、业绩证明等经确认图片资料。",
                    evidence_categories=["企业证件", "人员证件", "业绩"],
                )
            )
    for section in bid_template.appendix_sections:
        if any(keyword in section.title for keyword in ("平面", "布置", "图")):
            slots.append(
                TemplateSlot(
                    section_title=section.title,
                    slot_type="knowledge_image",
                    description="插入施工平面布置、现场组织或相关附图。",
                    evidence_categories=["图片资料", "施工方案"],
                )
            )
    return _dedupe_slots(slots)


def _infer_table_slots(bid_template: BidTemplate) -> list[TemplateSlot]:
    slots: list[TemplateSlot] = []
    for section in bid_template.main_sections + bid_template.appendix_sections:
        title = section.title
        if any(keyword in title for keyword in ("表", "清单", "计划", "机构", "资格")):
            slots.append(
                TemplateSlot(
                    section_title=title,
                    slot_type="markdown_table",
                    description="使用正式投标文件表格承载清单、计划、人员、机械、附表或资格响应内容。",
                    evidence_categories=["表格附件", "施工方案", "企业资料"],
                )
            )
    return _dedupe_slots(slots)


def _volume_for_section(title: str, section_type: str) -> str:
    combined = f"{title} {section_type}"
    if any(keyword in combined for keyword in ("报价", "清单", "投标总价", "price")):
        return "报价文件"
    if section_type == "construction_design" or "施工组织设计" in title:
        return "技术文件"
    if section_type == "appendix":
        return "技术文件"
    return "商务文件"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def _dedupe_slots(slots: list[TemplateSlot]) -> list[TemplateSlot]:
    seen: set[tuple[str, str]] = set()
    result: list[TemplateSlot] = []
    for slot in slots:
        key = (slot.section_title, slot.slot_type)
        if key not in seen:
            result.append(slot)
            seen.add(key)
    return result
