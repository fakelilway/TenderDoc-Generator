from __future__ import annotations

from agents.pricing_agent import PRICING_SYSTEM_PROMPT
from agents.reviewer_agent import REVIEWER_SYSTEM_PROMPT
from agents.scoring_agent import SCORING_SYSTEM_PROMPT
from prompts.generator_prompt import GENERATOR_SYSTEM_PROMPT
from prompts.parser_prompt import PARSER_SYSTEM_PROMPT




def test_generator_persona_is_real_bid_writer_not_generic_assistant() -> None:
    assert "真实投标文件总编" in GENERATOR_SYSTEM_PROMPT
    assert "施工组织设计主笔" in GENERATOR_SYSTEM_PROMPT
    assert "商务标合规顾问" in GENERATOR_SYSTEM_PROMPT
    assert "招标文件格式要求" in GENERATOR_SYSTEM_PROMPT
    assert "公司风格案例不得覆盖招标文件格式要求" in GENERATOR_SYSTEM_PROMPT
