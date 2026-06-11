from agents.template_profile_agent import build_template_profile
from schemas.bid_template import BidTemplate, BidTemplateSection


def test_build_template_profile_summarizes_case_bid_structure() -> None:
    template = BidTemplate(
        template_name="公路第一信封模板",
        source_file="road.pdf",
        page_count=100,
        envelope_type="第一信封",
        document_type="投标文件（商务及技术文件）",
        main_sections=[
            BidTemplateSection(title="一、投标函及投标函附录", section_type="fixed_form"),
            BidTemplateSection(title="五、施工组织设计", section_type="construction_design"),
            BidTemplateSection(title="八、资格审查资料", section_type="qualification"),
        ],
        construction_design_sections=[
            BidTemplateSection(title="第一章、总体施工组织布置及规划", level=1),
        ],
        appendix_sections=[
            BidTemplateSection(title="附表一、施工总体计划表", section_type="appendix"),
        ],
        fixed_form_sections=[
            BidTemplateSection(title="八、资格审查资料", section_type="qualification"),
        ],
    )

    profile = build_template_profile(
        template,
        project_type="公路工程",
        specialty="道路",
    )

    assert profile.template_name == "公路第一信封模板"
    assert profile.project_type == "公路工程"
    assert "五、施工组织设计" in profile.section_order
    assert "八、资格审查资料" in profile.fixed_forms
    assert "附表一、施工总体计划表" in profile.appendix_tables
    assert any(slot.slot_type == "knowledge_image" for slot in profile.image_slots)
    assert any(slot.slot_type == "markdown_table" for slot in profile.table_slots)
    assert "系统不自动" in profile.forbidden_phrases
    assert any("正式投标文件语气" in rule for rule in profile.tone_rules)
