from __future__ import annotations

from agents.pricing_agent import PRICING_SYSTEM_PROMPT
from agents.reviewer_agent import REVIEWER_SYSTEM_PROMPT
from agents.scoring_agent import SCORING_SYSTEM_PROMPT
from prompts.generator_prompt import GENERATOR_WRITER_SYSTEM_PROMPT, GENERATION_AUDITOR_SYSTEM_PROMPT, build_volume_agent_prompt
from prompts.parser_prompt import PARSER_SYSTEM_PROMPT
from schemas.tender import TenderRequirements


def test_generator_persona_is_real_bid_writer_not_generic_assistant() -> None:
    assert "投标文件主笔" in GENERATOR_WRITER_SYSTEM_PROMPT
    assert "不编造" in GENERATOR_WRITER_SYSTEM_PROMPT
    assert "审查员" in GENERATION_AUDITOR_SYSTEM_PROMPT
    assert "不输出 Markdown" in GENERATION_AUDITOR_SYSTEM_PROMPT
    prompt = build_volume_agent_prompt(
        volume="commercial",
        requirements=TenderRequirements(project_name="测试项目"),
        company_name="测试公司",
        document_outline=[],
    )
    user = prompt[1]["content"]
    assert "节点不可变" in user
    assert "表单照抄" in user
    assert "不知道的留空" in user
    assert "________" in user
