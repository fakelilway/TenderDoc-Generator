from __future__ import annotations

from agents.pricing_agent import PRICING_SYSTEM_PROMPT
from agents.reviewer_agent import REVIEWER_SYSTEM_PROMPT
from agents.scoring_agent import SCORING_SYSTEM_PROMPT
from prompts.generator_prompt import GENERATOR_SYSTEM_PROMPT
from prompts.parser_prompt import PARSER_SYSTEM_PROMPT


def test_all_agent_prompts_have_role_playing_experience_and_task_boundary() -> None:
    prompts = {
        "parser": PARSER_SYSTEM_PROMPT,
        "generator": GENERATOR_SYSTEM_PROMPT,
        "reviewer": REVIEWER_SYSTEM_PROMPT,
        "pricing": PRICING_SYSTEM_PROMPT,
        "scoring": SCORING_SYSTEM_PROMPT,
    }

    for agent_name, prompt in prompts.items():
        assert "角色扮演" in prompt, agent_name
        assert "经验背书" in prompt, agent_name
        assert "人格化工作方式" in prompt, agent_name
        assert "你的任务" in prompt, agent_name
        assert "不要编造" in prompt or "不得编造" in prompt or "不替生成 Agent 找借口" in prompt, agent_name


def test_generator_persona_is_real_bid_writer_not_generic_assistant() -> None:
    assert "真实投标文件总编" in GENERATOR_SYSTEM_PROMPT
    assert "施工组织设计主笔" in GENERATOR_SYSTEM_PROMPT
    assert "商务标合规顾问" in GENERATOR_SYSTEM_PROMPT
    assert "技术标必须排在商务标之前" in GENERATOR_SYSTEM_PROMPT
    assert "BidTemplate/outline 是唯一章节结构来源" in GENERATOR_SYSTEM_PROMPT
