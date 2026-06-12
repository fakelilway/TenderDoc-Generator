from types import SimpleNamespace

import pytest

from agents import generator_agent
from prompts.generator_prompt import (
    GENERATOR_SYSTEM_PROMPT,
    build_long_context_prompt,
    build_section_prompt,
    redact_pii,
)
from schemas.bid import BidSectionOutline
from schemas.bid_plan import BidPlan, BidPlanSection
from schemas.bid_template import BidTemplate, BidTemplateSection
from schemas.tender import RequirementItem, TenderRequirements
from utils.docx_exporter import VOLUME_MARKERS, split_delivery_markdown


def _test_settings(
    *,
    enable_llm_generation: bool = False,
    bid_generation_mode: str = "section",
    bid_template_path: str = "templates/bid_templates/road_first_envelope_template.json",
):
    return SimpleNamespace(
        company_name="安徽正奇建设有限公司",
        enable_llm_generation=enable_llm_generation,
        bid_generation_mode=bid_generation_mode,
        bid_template_path=bid_template_path,
    )


@pytest.fixture(autouse=True)
def _default_no_real_llm(monkeypatch):
    monkeypatch.setattr(generator_agent, "get_settings", lambda: _test_settings())


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="星河湾二期高层住宅施工总承包项目",
        tenderer_name="星河湾置业有限公司",
        project_location="星河湾片区",
        tender_scope="高层住宅土建、安装、装饰及室外配套工程施工",
        planned_duration="300日历天",
        quality_standard="合格",
        safety_target="无安全责任事故",
        bid_format_requirements="- 投标文件包括商务文件、技术文件、报价文件\n- 投标文件正本一份，副本四份",
        qualification_list=[RequirementItem(title="企业资质", description="建筑工程施工总承包一级")],
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 30 分"),
            RequirementItem(title="质量保证措施", description="质量保证措施 10 分"),
            RequirementItem(title="工期计划", description="进度计划 10 分"),
        ],
        invalid_bid_items=[RequirementItem(title="无效投标", description="未提交保证金按无效投标处理")],
    )


def _bid_template() -> BidTemplate:
    return BidTemplate(
        template_name="自定义模板",
        source_file="template.pdf",
        page_count=12,
        envelope_type="第一信封",
        document_type="投标文件（商务及技术文件）",
        main_sections=[
            BidTemplateSection(title="一、投标函及投标函附录", section_type="fixed_form"),
            BidTemplateSection(title="五、施工组织设计", section_type="construction_design"),
            BidTemplateSection(title="八、资格审查资料", section_type="qualification"),
        ],
        construction_design_sections=[
            BidTemplateSection(title="第一章、总体施工组织布置及规划", level=1),
            BidTemplateSection(title="第二章、专项交通导改与保通方案", level=1),
        ],
        appendix_sections=[
            BidTemplateSection(title="附表一、施工总体计划表", section_type="appendix"),
        ],
        fixed_form_sections=[
            BidTemplateSection(title="一、投标函及投标函附录", section_type="fixed_form"),
            BidTemplateSection(title="八、资格审查资料", section_type="qualification"),
        ],
    )


def _disable_real_llm(monkeypatch) -> None:
    monkeypatch.setattr(generator_agent, "get_settings", lambda: _test_settings())


def _enable_llm_generation(monkeypatch, mode: str = "long_context") -> None:
    monkeypatch.setattr(
        generator_agent,
        "get_settings",
        lambda: _test_settings(
            enable_llm_generation=True,
            bid_generation_mode=mode,
            bid_template_path=""
            if mode == "section"
            else "templates/bid_templates/road_first_envelope_template.json",
        ),
    )


def _mock_long_context(
    monkeypatch, markdown: str | None = None, captured: dict | None = None
) -> None:
    def fake_long_context(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return (
            markdown
            or f"""# 星河湾二期高层住宅施工总承包项目 投标文件

{VOLUME_MARKERS["commercial"]}

# 星河湾二期高层住宅施工总承包项目 商务文件

投标人：安徽正奇建设有限公司
致：星河湾置业有限公司
我单位承诺响应招标文件商务要求，计划工期 300日历天。

{VOLUME_MARKERS["technical"]}

# 星河湾二期高层住宅施工总承包项目 技术文件

## 施工组织设计

长上下文生成的施工组织设计正文。

{VOLUME_MARKERS["pricing"]}

# 星河湾二期高层住宅施工总承包项目 报价文件

## 报价文件

投标报价详见已标价工程量清单。
"""
        )

    monkeypatch.setattr(
        generator_agent, "_generate_long_context_with_llm", fake_long_context
    )


def test_build_bid_outline_uses_technical_score_items() -> None:
    outline = generator_agent.build_bid_outline(_requirements())
    titles = [section.title for section in outline]

    assert "第一章、总体施工组织布置及规划" in titles
    assert "第三章、工期保证体系及保证措施" in titles
    assert "第四章、工程质量管理体系及保证措施" in titles


def test_generator_prompt_defines_role_experience_and_task() -> None:
    assert "角色扮演" in GENERATOR_SYSTEM_PROMPT
    assert "经验背书" in GENERATOR_SYSTEM_PROMPT
    assert "你的任务" in GENERATOR_SYSTEM_PROMPT


def test_generator_prompt_forbids_reusing_sample_personal_data() -> None:
    assert "知识库/RAG 样本中出现的人名、身份证号、电话、证书编号、具体金额等只属于历史样本" in GENERATOR_SYSTEM_PROMPT
    assert "一律不得作为本项目事实写入正文，相应位置使用下划线空白" in GENERATOR_SYSTEM_PROMPT


def test_redact_pii_masks_citizen_ids_and_mobile_numbers() -> None:
    text = "项目经理张三，身份证号342401199001011234，联系电话13812345678，证书有效。"
    redacted = redact_pii(text)

    assert "342401199001011234" not in redacted
    assert "13812345678" not in redacted
    assert "████" in redacted
    assert "证书有效" in redacted
    # Trailing-X citizen IDs are masked too.
    assert "34240119900101123X" not in redact_pii("身份证号34240119900101123X")


def test_section_prompt_redacts_pii_from_retrieved_chunks() -> None:
    messages = build_section_prompt(
        "第一章、总体施工组织布置及规划",
        _requirements(),
        ["项目经理李四，身份证号110101198801012345，手机号15987654321。"],
    )
    user_prompt = messages[1]["content"]

    assert "110101198801012345" not in user_prompt
    assert "15987654321" not in user_prompt
    assert "████" in user_prompt


def test_build_bid_outline_maps_input_to_company_template() -> None:
    requirements = TenderRequirements(
        technical_score_items=[
            RequirementItem(title="安全文明施工", description="安全文明施工 15 分")
        ]
    )

    outline = generator_agent.build_bid_outline(requirements)

    safety = next(
        section for section in outline if section.title == "第五章、安全生产管理体系及保证措施"
    )
    assert safety.focus_points == ["安全文明施工 15 分"]
    assert outline[0].title == "第一章、总体施工组织布置及规划"


def test_build_bid_outline_prefers_bid_template_titles() -> None:
    requirements = TenderRequirements(
        technical_score_items=[
            RequirementItem(title="交通导改", description="交通导改与保通方案 20 分")
        ]
    )

    outline = generator_agent.build_bid_outline(requirements, _bid_template())

    assert [section.title for section in outline] == [
        "第一章、总体施工组织布置及规划",
        "第二章、专项交通导改与保通方案",
    ]
    assert outline[1].focus_points == ["交通导改与保通方案 20 分"]


def test_build_bid_outline_caps_mvp_section_count() -> None:
    requirements = TenderRequirements(
        technical_score_items=[
            RequirementItem(title=f"专项技术评分 {index}", description=f"专项要求 {index}")
            for index in range(20)
        ]
    )

    outline = generator_agent.build_bid_outline(requirements)

    assert len(outline) == generator_agent.MAX_OUTLINE_SECTIONS
    assert len(outline) == len(generator_agent.BID_TEMPLATE_SECTION_TITLES)


def test_build_bid_outline_does_not_cap_real_bid_template() -> None:
    template = _bid_template()
    template.construction_design_sections = [
        BidTemplateSection(title=f"第{index}章、模板专项章节", level=1)
        for index in range(generator_agent.MAX_OUTLINE_SECTIONS + 3)
    ]

    outline = generator_agent.build_bid_outline(_requirements(), template)

    assert len(outline) == generator_agent.MAX_OUTLINE_SECTIONS + 3
    assert outline[-1].title == f"第{generator_agent.MAX_OUTLINE_SECTIONS + 2}章、模板专项章节"


def test_build_bid_document_outline_includes_business_technical_and_price_gap() -> None:
    outline = generator_agent.build_bid_document_outline(
        _requirements(), _bid_template()
    )

    titles = [section.title for section in outline]
    assert "一、投标函及投标函附录" in titles
    assert "五、施工组织设计" in titles
    assert "八、资格审查资料" in titles
    assert "附图附表" in titles
    assert "报价文件（第二信封/经济标，如招标文件要求）" in titles

    technical = next(section for section in outline if section.title == "五、施工组织设计")
    assert technical.volume == "技术标"
    assert [child.title for child in technical.children] == [
        "第一章、总体施工组织布置及规划",
        "第二章、专项交通导改与保通方案",
    ]

    price = next(
        section
        for section in outline
        if section.section_type == "price_missing_template"
    )
    assert price.required is False
    assert "正式报价文件" in price.focus_points[0]


def test_generate_bid_section_fallback_has_markdown_and_no_placeholder(monkeypatch):
    monkeypatch.setattr(
        generator_agent,
        "_generate_section_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    markdown = generator_agent.generate_bid_section(
        "第一章、总体施工组织布置及规划",
        _requirements(),
        ["类似高层住宅项目施工组织设计经验。"],
    )

    assert markdown.startswith("## 第一章、总体施工组织布置及规划")
    assert "星河湾二期" in markdown
    assert "待补充" not in markdown


def test_structured_evidence_chunks_do_not_render_as_text(monkeypatch):
    _enable_llm_generation(monkeypatch)
    captured = {}
    _mock_long_context(
        monkeypatch,
        markdown=f"""# 星河湾二期高层住宅施工总承包项目 投标文件

{VOLUME_MARKERS["commercial"]}

# 商务文件

我单位承诺响应招标文件商务要求。

{VOLUME_MARKERS["technical"]}

# 技术文件

## 人员证件

{{{{knowledge_image:document_id=36 caption="江舟建安B证"}}}}

{VOLUME_MARKERS["pricing"]}

# 报价文件

投标报价详见已标价工程量清单。
""",
        captured=captured,
    )
    evidence = generator_agent.RetrievalResult(
        chunk_id=541,
        document_id=36,
        content="资料名称：3.江舟建安B\n资料类别：人员证件\n证件/证明：安全生产许可证\n图片用途：允许作为标书插图候选",
        metadata={
            "file_name": "3.江舟建安B.jpeg",
            "file_type": "jpeg",
            "ingestion_mode": "structured_evidence",
            "indexing_status": "structured_evidence",
        },
        distance=0.1,
        score=0.9,
    )

    package = generator_agent.generate_bid_package(
        _requirements(),
        {"第一章、总体施工组织布置及规划": [evidence]},
        knowledge_images=[
            {
                "document_id": 36,
                "file_name": "3.江舟建安B.jpeg",
                "caption": "江舟建安B证",
                "document_category": "人员证件",
                "certificate_type": "安全生产许可证",
                "tags": [],
            }
        ],
    )

    assert "资料名称：3.江舟建安B" not in package.combined_markdown
    assert "证件/证明：安全生产许可证" not in package.combined_markdown
    assert "{{knowledge_image:document_id=36" in package.combined_markdown
    assert "江舟建安B证" in package.combined_markdown
    assert captured["knowledge_chunks"] == []


def test_bid_plan_filters_images_before_long_context_generation(monkeypatch):
    _enable_llm_generation(monkeypatch)
    captured = {}
    _mock_long_context(monkeypatch, captured=captured)
    template = _bid_template()
    useful = generator_agent.RetrievalResult(
        chunk_id=22,
        document_id=102,
        content="施工组织设计有效素材",
        metadata={"file_name": "技术方案.docx"},
        distance=0.1,
        score=0.9,
    )
    unrelated = generator_agent.RetrievalResult(
        chunk_id=99,
        document_id=199,
        content="不属于本章节的商务资料",
        metadata={"file_name": "商务资料.docx"},
        distance=0.2,
        score=0.8,
    )
    plan = BidPlan(
        sections=[
            BidPlanSection(
                title="第一章、总体施工组织布置及规划",
                evidence_chunk_ids=[22],
                image_document_ids=[36],
            )
        ]
    )

    generator_agent.generate_bid_package(
        _requirements(),
        {"第一章、总体施工组织布置及规划": [useful, unrelated]},
        bid_template=template,
        knowledge_images=[
            {"document_id": 36, "caption": "施工平面图", "tags": ["施工平面图"]},
            {"document_id": 77, "caption": "无关图片", "tags": ["无关"]},
        ],
        bid_plan=plan,
    )

    assert captured["knowledge_images"] == [
        {"document_id": 36, "caption": "施工平面图", "tags": ["施工平面图"]}
    ]


def test_generate_bid_package_requires_llm_enabled(monkeypatch):
    _disable_real_llm(monkeypatch)

    with pytest.raises(generator_agent.GeneratorAgentError, match="Local fallback"):
        generator_agent.generate_bid_package(_requirements(), {})


def test_generate_bid_package_combined_markdown_carries_lossless_volume_markers(
    monkeypatch,
):
    _enable_llm_generation(monkeypatch)
    _mock_long_context(monkeypatch)

    package = generator_agent.generate_bid_package(
        _requirements(),
        {},
        bid_template=_bid_template(),
    )
    markdown = package.combined_markdown

    for key in ("commercial", "technical", "pricing"):
        assert VOLUME_MARKERS[key] in markdown

    volumes = split_delivery_markdown(markdown)
    assert volumes["commercial"] == package.commercial_markdown.strip()
    assert volumes["technical"] == package.technical_markdown.strip()
    assert volumes["pricing"] == package.pricing_markdown.strip()


def test_generate_bid_package_passes_template_outline_to_long_context(monkeypatch):
    _enable_llm_generation(monkeypatch)
    captured = {}
    _mock_long_context(monkeypatch, captured=captured)

    package = generator_agent.generate_bid_package(
        _requirements(),
        {},
        bid_template=_bid_template(),
    )

    outline_titles = [item["title"] for item in captured["document_outline"]]
    assert "一、投标函及投标函附录" in outline_titles
    assert "五、施工组织设计" in outline_titles
    assert "附图附表" in outline_titles
    assert package.generation_mode == "long_context"


def test_generate_bid_package_uses_long_context_for_all_volumes(monkeypatch):
    _enable_llm_generation(monkeypatch)
    _mock_long_context(monkeypatch)

    package = generator_agent.generate_bid_package(_requirements(), {})
    markdown = package.combined_markdown

    assert markdown.startswith("# 星河湾二期高层住宅施工总承包项目 投标文件")
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "长上下文生成的施工组织设计正文" in package.technical_markdown
    assert "我单位承诺响应招标文件商务要求" in package.commercial_markdown
    assert "投标报价详见已标价工程量清单" in package.pricing_markdown


def test_technical_volume_keeps_manual_image_slots(monkeypatch):
    monkeypatch.setattr(
        generator_agent,
        "generate_bid_section",
        lambda section_title, requirements, chunks: f"## {section_title}\n\n技术正文。",
    )
    outline = [
        BidSectionOutline(
            title="施工总平面布置",
            manual_image_slots=[
                {
                    "title": "施工总平面布置图",
                    "placement": "第一章 第二节",
                    "description": "人工插入现场总平面图。",
                }
            ],
        )
    ]

    markdown = "\n".join(
        generator_agent._technical_volume_from_outline(
            _requirements(),
            outline,
            {},
            use_local_section_fallback=False,
        )
    )

    assert "#### 手动插图预留" in markdown
    assert "【人工插图 1】施工总平面布置图" in markdown
    assert "插入位置：第一章 第二节" in markdown
    assert "图片说明：人工插入现场总平面图。" in markdown


def test_generate_bid_package_separates_business_technical_and_pricing(monkeypatch):
    _enable_llm_generation(monkeypatch)
    requirements = TenderRequirements(
        project_name="萧县2025年农村公路提质改造联网路工程",
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 40 分")
        ],
    )
    _mock_long_context(
        monkeypatch,
        markdown=f"""# 萧县2025年农村公路提质改造联网路工程 投标文件

{VOLUME_MARKERS["commercial"]}

# 萧县2025年农村公路提质改造联网路工程 商务文件

投标人：安徽正奇建设有限公司

{VOLUME_MARKERS["technical"]}

# 萧县2025年农村公路提质改造联网路工程 技术文件

## 施工组织设计

施工组织技术正文。

{VOLUME_MARKERS["pricing"]}

# 萧县2025年农村公路提质改造联网路工程 报价文件

报价文件目录。
""",
    )

    package = generator_agent.generate_bid_package(requirements, {})

    markdown = package.combined_markdown
    assert markdown.startswith("# 萧县2025年农村公路提质改造联网路工程 投标文件")
    assert "见投标人须知前附表 投标文件" not in markdown
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "施工组织技术正文" in package.technical_markdown
    assert "施工组织技术正文" not in package.commercial_markdown
    assert "报价文件目录" in package.pricing_markdown


def test_sanitize_bid_markdown_removes_meta_and_rag_noise() -> None:
    raw = (
        "# 投标文件\n\n"
        "## 一、技术标\n"
        "我单位承诺严格响应招标文件要求。\n"
        "⚠️人工确认点：【待补充】投标总价、保证金金额。\n"
        "投标总报价为：⚠️人工确认点：【待补充】按清单计算。\n"
        "本章响应度自查：完全满足\n"
        "第13页/共892页\n"
        "……\n"
        "## 三、废标风险逐条响应自查表\n"
        "| 序号 | 风险条款 | 人工确认点 |\n"
        "本部分仅生成报价文件目录和编制说明，系统不自动生成任何报价数值。\n"
        "本附表按招标文件和真实投标模板要求设置，用于支撑施工组织设计。\n"
    )

    cleaned = generator_agent.sanitize_bid_markdown(raw)

    assert "人工确认点" not in cleaned
    assert "待补充" not in cleaned
    assert "本章响应度自查" not in cleaned
    assert "废标风险逐条响应自查表" not in cleaned
    assert "本部分仅生成" not in cleaned
    assert "真实投标模板" not in cleaned
    assert "系统不自动" not in cleaned
    assert "第13页/共892页" not in cleaned
    # Real content is preserved; the fill-in blank replaces the marker.
    assert "我单位承诺严格响应招标文件要求。" in cleaned
    assert "________" in cleaned


def test_long_context_output_is_sanitized_before_delivery(monkeypatch):
    _enable_llm_generation(monkeypatch)
    _mock_long_context(
        monkeypatch,
        markdown=f"""# 星河湾二期高层住宅施工总承包项目 投标文件

{VOLUME_MARKERS["commercial"]}

# 商务文件

本部分仅生成报价文件目录和编制说明，系统不自动生成任何报价数值。
我单位承诺响应招标文件商务要求。

{VOLUME_MARKERS["technical"]}

# 技术文件

本附表按招标文件和真实投标模板要求设置。
我单位将按施工组织设计组织实施。

{VOLUME_MARKERS["pricing"]}

# 报价文件

投标报价详见已标价工程量清单。
""",
    )
    package = generator_agent.generate_bid_package(
        _requirements(),
        {},
        bid_template=_bid_template(),
    )

    markdown = package.combined_markdown
    forbidden = [
        "本附表按招标文件和真实投标模板要求设置",
        "填报要求",
        "由项目技术负责人按最终施工部署复核填写",
        "本部分仅生成",
        "系统不自动",
        "由造价人员",
    ]
    for phrase in forbidden:
        assert phrase not in markdown
    assert "我单位承诺响应招标文件商务要求。" in markdown
    assert "我单位将按施工组织设计组织实施。" in markdown
    assert "投标报价详见已标价工程量清单。" in markdown


def test_generator_prompt_embeds_real_format_spec_and_forbids_meta() -> None:
    assert "真实投标文件文风与正文规范" in GENERATOR_SYSTEM_PROMPT
    assert "招标文件格式要求决定卷册、表单和签章等强制结构" in GENERATOR_SYSTEM_PROMPT
    assert "知识库/RAG 只提供真实资料和措辞素材" in GENERATOR_SYSTEM_PROMPT
    assert "BidTemplate JSON 是唯一章节结构来源" not in GENERATOR_SYSTEM_PROMPT
    assert "严禁输出" in GENERATOR_SYSTEM_PROMPT
    # The prompt no longer mandates emitting authoring meta-text.
    assert "必须使用“⚠️人工确认点" not in GENERATOR_SYSTEM_PROMPT

    messages = build_section_prompt(
        "第一章、总体施工组织布置及规划",
        _requirements(),
        ["第13页/共892页\n施工总体部署说明。\n……"],
    )
    user_prompt = messages[1]["content"]
    assert "写作约束必须遵守" in user_prompt
    # Leaked RAG page footers / dot leaders are cleaned out of injected chunks.
    assert "第13页/共892页" not in user_prompt
    assert "施工总体部署说明。" in user_prompt


def test_long_context_prompt_uses_volume_contract_and_selected_materials() -> None:
    messages = build_long_context_prompt(
        requirements=_requirements(),
        company_name="安徽正奇建设有限公司",
        document_outline=[
            {
                "title": "五、施工组织设计",
                "volume": "技术标",
                "section_type": "construction_design",
                "children": [{"title": "第一章、总体施工组织布置及规划"}],
            }
        ],
        knowledge_chunks=[
            {
                "section_title": "第一章、总体施工组织布置及规划",
                "title": "类似工程施工方案.docx",
                "content": "第13页/共892页\n施工总体部署经验。\n13812345678",
            }
        ],
        knowledge_images=[{"document_id": 36, "caption": "营业执照", "tags": ["公司证件"]}],
        tender_text="招标范围：道路改造、排水及交通安全设施。计划工期180日历天，质量标准为合格。",
    )
    prompt = messages[1]["content"]

    assert "<!-- tdg:volume:commercial -->" in prompt
    assert "<!-- tdg:volume:technical -->" in prompt
    assert "<!-- tdg:volume:pricing -->" in prompt
    assert "五、施工组织设计" in prompt
    assert "类似工程施工方案.docx" in prompt
    assert "施工总体部署经验。" in prompt
    assert "道路改造、排水及交通安全设施" in prompt
    assert "计划工期180日历天" in prompt
    assert "第13页/共892页" not in prompt
    assert "13812345678" not in prompt
    assert "{{knowledge_image:document_id=36" in prompt


def test_long_context_prompt_includes_extracted_conditions_and_manual_fields() -> None:
    messages = build_long_context_prompt(
        requirements=_requirements(),
        company_name="安徽正奇建设有限公司",
        document_outline=[],
        pricing_strategy={
            "payment_terms": [{"name": "付款条件", "source_text": "工程进度款按月支付80%"}],
            "guarantee_requirements": [],
            "extracted_conditions": [
                {"name": "工期约束", "source_text": "计划工期300日历天"},
                {"name": "报价/评标价约束", "source_text": "最高限价5000万元"},
            ],
            "manual_fields": [
                {"label": "投标总价", "reason": "必须由人工根据成本测算确认"},
            ],
        },
        knowledge_chunks=[],
    )
    prompt = messages[1]["content"]

    assert "工程进度款按月支付80%" in prompt
    assert "计划工期300日历天" in prompt
    assert "最高限价5000万元" in prompt
    assert "投标总价" in prompt


def test_long_context_llm_continues_on_truncation(monkeypatch) -> None:
    from agents import generator_agent

    class FakeChoice:
        def __init__(self, content: str, finish_reason: str) -> None:
            class Message:
                pass

            self.message = Message()
            self.message.content = content
            self.finish_reason = finish_reason

    class FakeResponse:
        def __init__(self, content: str, finish_reason: str) -> None:
            self.choices = [FakeChoice(content, finish_reason)]

    calls: list[list[dict]] = []
    responses = [
        FakeResponse("# 前半部分\n\n商务内容", "length"),
        FakeResponse("后半部分内容", "stop"),
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs["messages"])
            return responses[len(calls) - 1]

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(generator_agent, "OpenAI", FakeClient)
    monkeypatch.setattr(generator_agent, "_has_real_key", lambda value: bool(value))
    monkeypatch.setattr(
        generator_agent,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="sk-test",
            openrouter_base_url="https://example.test/v1",
            openrouter_model="test-model",
            bid_long_context_timeout_seconds=10.0,
            bid_long_context_max_tokens=100,
        ),
    )

    content = generator_agent._generate_long_context_with_llm(
        requirements=_requirements(),
        company_name="测试公司",
        document_outline=[],
        bid_plan=None,
        template_name="",
        pricing_strategy=None,
        knowledge_chunks=[],
    )

    assert "前半部分" in content and "后半部分内容" in content
    assert len(calls) == 2
    # 续写请求必须带上已生成内容和继续指令
    assert calls[1][-2]["role"] == "assistant"
    assert calls[1][-1]["role"] == "user"
    assert "继续输出" in calls[1][-1]["content"]


def test_long_context_llm_raises_when_still_truncated(monkeypatch) -> None:
    from agents import generator_agent

    class FakeChoice:
        def __init__(self) -> None:
            class Message:
                pass

            self.message = Message()
            self.message.content = "永远截断的内容"
            self.finish_reason = "length"

    class FakeResponse:
        def __init__(self) -> None:
            self.choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(generator_agent, "OpenAI", FakeClient)
    monkeypatch.setattr(generator_agent, "_has_real_key", lambda value: bool(value))
    monkeypatch.setattr(
        generator_agent,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="sk-test",
            openrouter_base_url="https://example.test/v1",
            openrouter_model="test-model",
            bid_long_context_timeout_seconds=10.0,
            bid_long_context_max_tokens=100,
        ),
    )

    with pytest.raises(generator_agent.GeneratorAgentError, match="截断"):
        generator_agent._generate_long_context_with_llm(
            requirements=_requirements(),
            company_name="测试公司",
            document_outline=[],
            bid_plan=None,
            template_name="",
            pricing_strategy=None,
            knowledge_chunks=[],
        )


def test_generate_bid_package_prefers_long_context_kernel(monkeypatch) -> None:
    _enable_llm_generation(monkeypatch, mode="long_context")

    def fake_long_context(**kwargs):
        return f"""# 星河湾二期高层住宅施工总承包项目 投标文件

{VOLUME_MARKERS["commercial"]}

# 星河湾二期高层住宅施工总承包项目 商务文件

## 一、投标函

我单位承诺响应招标文件商务要求。

{VOLUME_MARKERS["technical"]}

# 星河湾二期高层住宅施工总承包项目 技术文件

## 五、施工组织设计

长上下文生成的施工组织设计正文。

{VOLUME_MARKERS["pricing"]}

# 星河湾二期高层住宅施工总承包项目 报价文件

## 报价文件

投标报价详见已标价工程量清单。
"""

    monkeypatch.setattr(
        generator_agent,
        "_generate_long_context_with_llm",
        fake_long_context,
    )

    package = generator_agent.generate_bid_package(_requirements(), {})

    assert "长上下文生成的施工组织设计正文" in package.technical_markdown
    assert "我单位承诺响应招标文件商务要求" in package.commercial_markdown
    assert "投标报价详见已标价工程量清单" in package.pricing_markdown
    assert VOLUME_MARKERS["commercial"] in package.combined_markdown


def test_generate_bid_package_raises_when_long_context_fails(monkeypatch) -> None:
    _enable_llm_generation(monkeypatch, mode="long_context")
    monkeypatch.setattr(
        generator_agent,
        "_generate_long_context_with_llm",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("model timeout")),
    )

    with pytest.raises(RuntimeError, match="model timeout"):
        generator_agent.generate_bid_package(_requirements(), {})
