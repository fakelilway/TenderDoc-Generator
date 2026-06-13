from types import SimpleNamespace

import pytest

from agents import generator_agent
from prompts.generator_prompt import (
    GENERATOR_SYSTEM_PROMPT,
    build_bid_framework_brief,
    build_generation_audit_prompt,
    build_volume_agent_prompt,
    build_volume_revision_prompt,
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
bid_template_path: str = "templates/bid_templates/road_first_envelope_template.json",
):
    return SimpleNamespace(
        company_name="安徽正奇建设有限公司",
        enable_llm_generation=enable_llm_generation,
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


def _enable_llm_generation(monkeypatch, mode: str = "multi_agent") -> None:
    monkeypatch.setattr(
        generator_agent,
        "get_settings",
        lambda: _test_settings(enable_llm_generation=True)
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

    # mock the multi-agent flow
    monkeypatch.setattr(
        generator_agent, "_run_structure_audit_with_llm",
        lambda **kwargs: {"status": "pass", "summary": "结构匹配。", "issues": []}
    )
    monkeypatch.setattr(
        generator_agent, "build_bid_document_outline",
        lambda req, tmpl: []
    )
    monkeypatch.setattr(
        generator_agent, "_long_context_chunks",
        lambda x: []
    )


def _mock_multi_agent(monkeypatch, captured: dict | None = None) -> None:
    generated: list[str] = []
    revised: list[str] = []

    def fake_generate_volume(**kwargs):
        volume = kwargs["volume"]
        generated.append(volume)
        if captured is not None:
            captured.setdefault("volume_calls", []).append(kwargs)
        return {
            "commercial": "# 商务文件\n\n我单位承诺响应商务和资格要求。",
            "technical": "# 技术文件\n\n施工组织设计正文，包含质量、安全、进度措施。",
            "pricing": "# 报价文件\n\n投标报价详见已标价工程量清单，金额为________元。",
        }[volume]

    def fake_revise_volume(**kwargs):
        volume = kwargs["volume"]
        revised.append(volume)
        if captured is not None:
            captured.setdefault("revision_calls", []).append(kwargs)
        return kwargs["draft_markdown"] + f"\n\n{volume} revision checked."

    def fake_generation_audit(**kwargs):
        if captured is not None:
            captured.setdefault("audit_calls", []).append(kwargs)
        return {"status": "pass", "summary": "三卷符合框架。", "issues": []}

    def fake_structure_audit(**kwargs):
        if captured is not None:
            captured.setdefault("structure_audit_calls", []).append(kwargs)
        return {"status": "pass", "summary": "结构完全匹配。", "issues": []}

    monkeypatch.setattr(
        generator_agent, "_generate_volume_with_llm", fake_generate_volume
    )
    monkeypatch.setattr(generator_agent, "_revise_volume_with_llm", fake_revise_volume)
    monkeypatch.setattr(
        generator_agent, "_run_structure_audit_with_llm", fake_structure_audit
    )
    monkeypatch.setattr(
        generator_agent, "_run_generation_audit_with_llm", fake_generation_audit
    )
    if captured is not None:
        captured["generated"] = generated
        captured["revised"] = revised


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












def test_generate_bid_package_multi_agent_runs_volume_revision_and_audit(
    monkeypatch,
) -> None:
    _enable_llm_generation(monkeypatch, mode="multi_agent")
    captured: dict = {}
    _mock_multi_agent(monkeypatch, captured=captured)
    document_outline = [
        {
            "title": "人工确认技术目录",
            "volume": "技术标",
            "section_type": "construction_design",
            "children": [],
        }
    ]

    package = generator_agent.generate_bid_package(
        _requirements(),
        {},
        document_outline=document_outline,
        knowledge_images=[
            {
                "document_id": 101,
                "caption": "营业执照",
                "tags": ["公司证件"],
            },
            {
                "document_id": 202,
                "caption": "施工总平面图",
                "tags": ["附图"],
            },
            {
                "document_id": 303,
                "caption": "工程量清单报价表",
                "tags": ["报价"],
            },
        ],
    )

    assert set(captured["generated"]) == {"commercial", "technical", "pricing"}
    assert set(captured["revised"]) == {"commercial", "technical", "pricing"}
    assert len(captured["generated"]) == 3
    assert len(captured["revised"]) == 3
    volume_calls = {call["volume"]: call for call in captured["volume_calls"]}
    assert all(
        call["document_outline"] == document_outline for call in volume_calls.values()
    )
    assert {
        image["document_id"] for image in volume_calls["commercial"]["knowledge_images"]
    } == {101}
    assert {
        image["document_id"] for image in volume_calls["technical"]["knowledge_images"]
    } == {202}
    assert {
        image["document_id"] for image in volume_calls["pricing"]["knowledge_images"]
    } == {303}
    assert captured["audit_calls"][0]["technical_markdown"].startswith("# 技术文件")
    assert package.generation_mode == "multi_agent"
    assert "commercial revision checked" in package.commercial_markdown
    assert "technical revision checked" in package.technical_markdown
    assert "pricing revision checked" in package.pricing_markdown
    assert VOLUME_MARKERS["commercial"] in package.combined_markdown
    assert VOLUME_MARKERS["technical"] in package.combined_markdown
    assert VOLUME_MARKERS["pricing"] in package.combined_markdown


def test_generate_bid_package_multi_agent_fails_without_silent_fallback(
    monkeypatch,
) -> None:
    _enable_llm_generation(monkeypatch, mode="multi_agent")

    def fail_volume(**kwargs):
        raise generator_agent.GeneratorAgentError("commercial agent failed")

    monkeypatch.setattr(generator_agent, "_generate_volume_with_llm", fail_volume)

    with pytest.raises(
        generator_agent.GeneratorAgentError, match="commercial agent failed"
    ):
        generator_agent.generate_bid_package(_requirements(), {})


def test_generate_bid_package_multi_agent_revises_failed_audit(
    monkeypatch,
) -> None:
    _enable_llm_generation(monkeypatch, mode="multi_agent")
    audit_calls: list[dict] = []
    revision_calls: list[dict] = []

    def fake_generate_volume(**kwargs):
        return {
            "commercial": "# 商务文件\n\n## 投标函\n\n商务投标函。\n\n## 投标函（报价文件）\n\n错误越卷内容。",
            "technical": "# 技术文件\n\n施工组织设计正文。",
            "pricing": "# 报价文件\n\n投标报价详见已标价工程量清单。",
        }[kwargs["volume"]]

    def fake_revise_volume(**kwargs):
        revision_calls.append(kwargs)
        if kwargs["volume"] == "commercial" and kwargs.get("audit_feedback"):
            return "# 商务文件\n\n## 投标函\n\n商务投标函。"
        return kwargs["draft_markdown"]

    def fake_audit(**kwargs):
        audit_calls.append(kwargs)
        if len(audit_calls) == 1:
            return {
                "status": "revise",
                "summary": "商务卷包含报价卷投标函。",
                "issues": [
                    {
                        "volume": "commercial",
                        "severity": "major",
                        "problem": "商务卷出现不属于本卷的投标函（报价文件）。",
                        "revision_prompt": "删除商务卷中的报价文件投标函，只保留商务卷投标函。",
                    }
                ],
            }
        return {"status": "pass", "summary": "已修正。", "issues": []}

    monkeypatch.setattr(
        generator_agent, "_generate_volume_with_llm", fake_generate_volume
    )
    monkeypatch.setattr(generator_agent, "_revise_volume_with_llm", fake_revise_volume)
    monkeypatch.setattr(
        generator_agent,
        "_run_structure_audit_with_llm",
        lambda **kwargs: {"status": "pass", "summary": "结构匹配。", "issues": []},
    )
    monkeypatch.setattr(generator_agent, "_run_generation_audit_with_llm", fake_audit)

    package = generator_agent.generate_bid_package(_requirements(), {})

    assert len(audit_calls) == 2
    assert any(
        call["volume"] == "commercial" and "报价文件投标函" in call["audit_feedback"]
        for call in revision_calls
    )
    assert "错误越卷内容" not in package.commercial_markdown
    assert VOLUME_MARKERS["commercial"] in package.combined_markdown
