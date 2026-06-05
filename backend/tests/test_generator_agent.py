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
    assert "真实投标文件模板 JSON 决定“按照什么格式写”" in user_prompt
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
        section
        for section in outline
        if section.title == "第五章、安全生产管理体系及保证措施"
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

    assert markdown.startswith("# 星河湾二期高层住宅施工总承包项目 投标文件（技术标及商务标）")
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "【商务标】" in markdown
    assert "## 二、商务标" in markdown
    assert "### 4. 报价文件" in markdown
    assert "⚠️人工确认点：【待补充】" in markdown
    assert "【技术标】" in markdown
    assert "## 一、技术标" in markdown
    assert "### 技术标目录" in markdown
    assert "- 第一章、总体施工组织布置及规划" in markdown
    assert "## 三、废标风险逐条响应自查表" in markdown
    assert markdown.index("【技术标】") < markdown.index("【商务标】")


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
    assert "### 1. 施工组织设计" not in markdown


def test_generate_bid_document_prefers_single_document_llm(monkeypatch):
    _enable_llm_generation(monkeypatch)
    monkeypatch.setattr(
        generator_agent,
        "_generate_document_with_llm",
        lambda *args, **kwargs: "# 模板化技术文件\n\n## 施工组织设计目录\n",
    )

    markdown = generator_agent.generate_bid_document(_requirements(), {})

    assert markdown.startswith("# 星河湾二期高层住宅施工总承包项目 投标文件（技术标及商务标）")
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "## 二、商务标" in markdown
    assert "## 一、技术标" in markdown
    assert markdown.index("【技术标】") < markdown.index("【商务标】")


def test_generate_bid_document_rewrites_llm_placeholder_title(monkeypatch):
    _enable_llm_generation(monkeypatch)
    requirements = TenderRequirements(
        project_name="萧县2025年农村公路提质改造联网路工程",
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 40 分")
        ],
    )
    monkeypatch.setattr(
        generator_agent,
        "_generate_document_with_llm",
        lambda *args, **kwargs: (
            "# 见投标人须知前附表 投标文件（技术文件）\n\n"
            "## 施工组织设计目录\n"
        ),
    )

    markdown = generator_agent.generate_bid_document(requirements, {})

    assert markdown.startswith("# 萧县2025年农村公路提质改造联网路工程 投标文件（技术标及商务标）")
    assert "见投标人须知前附表 投标文件" not in markdown
    assert "投标人：安徽正奇建设有限公司" in markdown
    assert "## 二、商务标" in markdown
    assert markdown.index("【技术标】") < markdown.index("【商务标】")
