from prompts.generator_prompt import build_long_context_prompt
from schemas.tender import TenderRequirements
from services.company_profile_service import company_profile_prompt_block


def test_prompt_block_renders_only_filled_fields():
    block = company_profile_prompt_block(
        {
            "company_name": "安徽正奇建设有限公司",
            "legal_representative": "许明英",
            "registered_capital": "",
            "contact_phone": None,
        }
    )
    assert "- 公司名称：安徽正奇建设有限公司" in block
    assert "- 法定代表人：许明英" in block
    assert "注册资本" not in block
    assert "联系电话" not in block


def test_prompt_block_empty_profile_returns_empty():
    assert company_profile_prompt_block(None) == ""
    assert company_profile_prompt_block({}) == ""


def test_long_context_prompt_includes_profile_section():
    requirements = TenderRequirements(project_name="测试项目")
    messages = build_long_context_prompt(
        requirements=requirements,
        company_name="安徽正奇建设有限公司",
        document_outline=[],
        company_profile_block="- 公司名称：安徽正奇建设有限公司\n- 资质等级：公路工程施工总承包贰级",
    )
    user_prompt = messages[1]["content"]
    assert "投标人企业档案" in user_prompt
    assert "资质等级：公路工程施工总承包贰级" in user_prompt
    assert "禁止改写或留空" in user_prompt


def test_long_context_prompt_omits_profile_section_when_empty():
    requirements = TenderRequirements(project_name="测试项目")
    messages = build_long_context_prompt(
        requirements=requirements,
        company_name="安徽正奇建设有限公司",
        document_outline=[],
    )
    assert "投标人企业档案（已人工核实" not in messages[1]["content"]
