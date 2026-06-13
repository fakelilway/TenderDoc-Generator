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
