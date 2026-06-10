from types import SimpleNamespace

from agents import generator_agent
from prompts.generator_prompt import GENERATOR_SYSTEM_PROMPT, build_document_prompt
from schemas.bid_template import BidTemplate, BidTemplateSection
from schemas.tender import RequirementItem, TenderRequirements


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="星河湾二期高层住宅施工总承包项目",
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


def _enable_llm_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        generator_agent,
        "get_settings",
        lambda: SimpleNamespace(
            company_name="安徽正奇建设有限公司",
            enable_llm_generation=True,
        ),
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


def test_document_prompt_uses_template_priority_instead_of_hardcoded_format() -> None:
    messages = build_document_prompt(
        requirements=_requirements(),
        outline_titles=["第一章、总体施工组织布置及规划", "第二章、专项交通导改与保通方案"],
        retrieved_chunks=[],
        company_name="安徽正奇建设有限公司",
        bid_template=_bid_template(),
    )
    user_prompt = messages[1]["content"]

    assert "结构来源优先级" in user_prompt
    assert "BidTemplate JSON 是唯一章节结构来源" in user_prompt
    assert "知识库/RAG 只提供素材" in user_prompt
    assert "输出结构必须严格如下" not in user_prompt
    assert "### 1. 施工组织设计" not in user_prompt
    assert "第二章、专项交通导改与保通方案" in user_prompt
    assert "附表一、施工总体计划表" in user_prompt


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
    assert "系统不自动编造" in price.focus_points[0]


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


def test_generate_bid_document_uses_complete_bid_file_shell(monkeypatch):
    monkeypatch.setattr(
        generator_agent,
        "_generate_document_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        generator_agent,
        "generate_bid_section",
        lambda section_title, requirements, chunks: f"## {section_title}\n\n正文。",
    )

    markdown = generator_agent.generate_bid_document(_requirements(), {})

    assert markdown.startswith("# 星河湾二期高层住宅施工总承包项目 投标文件")
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "## 投标文件目录" in markdown
    assert "## 一、投标函及投标函附录" in markdown
    assert "## 五、施工组织设计" in markdown
    assert "## 报价文件（第二信封/经济标，如招标文件要求）" in markdown
    # Authoring meta-text must NOT leak into the production bid.
    assert "人工确认点" not in markdown
    assert "待补充" not in markdown
    assert "本章响应度自查" not in markdown
    assert "废标风险逐条响应自查表" not in markdown
    assert "### 施工组织设计目录" in markdown
    assert "- 第一章、总体施工组织布置及规划" in markdown
    assert markdown.index("## 一、投标函及投标函附录") < markdown.index("## 五、施工组织设计")


def test_generate_bid_document_includes_template_appendices(monkeypatch):
    monkeypatch.setattr(
        generator_agent,
        "_generate_document_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    markdown = generator_agent.generate_bid_document(
        _requirements(),
        {},
        bid_template=_bid_template(),
    )

    assert "- 第二章、专项交通导改与保通方案" in markdown
    assert "## 附图附表" in markdown
    assert "### 附表一、施工总体计划表" in markdown
    assert "## 一、投标函及投标函附录" in markdown
    assert "## 八、资格审查资料" in markdown
    assert markdown.index("## 一、投标函及投标函附录") < markdown.index("## 五、施工组织设计")
    assert "## 报价文件（第二信封/经济标，如招标文件要求）" in markdown
    assert "### 1. 施工组织设计" not in markdown


def test_generate_bid_document_prefers_single_document_llm(monkeypatch):
    _enable_llm_generation(monkeypatch)
    monkeypatch.setattr(
        generator_agent,
        "generate_bid_section",
        lambda section_title, requirements, chunks: f"## {section_title}\n\n技术正文。",
    )

    package = generator_agent.generate_bid_package(_requirements(), {})
    markdown = package.combined_markdown

    assert markdown.startswith("# 星河湾二期高层住宅施工总承包项目 投标文件")
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "## 二、商务标" in markdown
    assert "【技术文件】" in package.technical_markdown
    assert "【商务文件】" in package.commercial_markdown
    assert "【报价文件】" in package.pricing_markdown
    assert "技术正文" in package.technical_markdown
    assert "技术正文" not in package.commercial_markdown


def test_generate_bid_package_separates_business_technical_and_pricing(monkeypatch):
    _enable_llm_generation(monkeypatch)
    requirements = TenderRequirements(
        project_name="萧县2025年农村公路提质改造联网路工程",
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 40 分")
        ],
    )
    monkeypatch.setattr(
        generator_agent,
        "generate_bid_section",
        lambda section_title, requirements, chunks: f"## {section_title}\n\n施工组织技术正文。",
    )

    package = generator_agent.generate_bid_package(requirements, {})

    markdown = package.combined_markdown
    assert markdown.startswith("# 萧县2025年农村公路提质改造联网路工程 投标文件")
    assert "见投标人须知前附表 投标文件" not in markdown
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "## 二、商务标" in markdown
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
    )

    cleaned = generator_agent.sanitize_bid_markdown(raw)

    assert "人工确认点" not in cleaned
    assert "待补充" not in cleaned
    assert "本章响应度自查" not in cleaned
    assert "废标风险逐条响应自查表" not in cleaned
    assert "第13页/共892页" not in cleaned
    # Real content is preserved; the fill-in blank replaces the marker.
    assert "我单位承诺严格响应招标文件要求。" in cleaned
    assert "________" in cleaned


def test_generator_prompt_embeds_real_format_spec_and_forbids_meta() -> None:
    assert "真实投标文件文风与正文规范" in GENERATOR_SYSTEM_PROMPT
    assert "BidTemplate JSON 是唯一章节结构来源" in GENERATOR_SYSTEM_PROMPT
    assert "知识库/RAG 只提供措辞和素材" in GENERATOR_SYSTEM_PROMPT
    assert "严禁输出" in GENERATOR_SYSTEM_PROMPT
    # The prompt no longer mandates emitting authoring meta-text.
    assert "必须使用“⚠️人工确认点" not in GENERATOR_SYSTEM_PROMPT

    messages = build_document_prompt(
        requirements=_requirements(),
        outline_titles=["第一章、总体施工组织布置及规划"],
        retrieved_chunks=["第13页/共892页\n施工总体部署说明。\n……"],
        company_name="安徽正奇建设有限公司",
    )
    user_prompt = messages[1]["content"]
    assert "严禁事项" in user_prompt
    # Leaked RAG page footers / dot leaders are cleaned out of injected chunks.
    assert "第13页/共892页" not in user_prompt
    assert "施工总体部署说明。" in user_prompt
