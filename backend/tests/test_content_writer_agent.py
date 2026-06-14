from types import SimpleNamespace

from agents import content_writer_agent


def test_content_writer_respects_deepseek_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        content_writer_agent,
        "get_settings",
        lambda: SimpleNamespace(
            bid_llm_provider="deepseek",
            deepseek_api_key="sk-deepseek",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-pro",
            openrouter_api_key="sk-openrouter",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_model="deepseek/deepseek-v4-pro",
        ),
    )

    api_key, base_url, model = content_writer_agent._get_llm_client_config()

    assert api_key == "sk-deepseek"
    assert base_url == "https://api.deepseek.com"
    assert model == "deepseek-v4-pro"


def test_content_writer_respects_openrouter_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        content_writer_agent,
        "get_settings",
        lambda: SimpleNamespace(
            bid_llm_provider="openrouter",
            deepseek_api_key="sk-deepseek",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-pro",
            openrouter_api_key="sk-openrouter",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_model="deepseek/deepseek-v4-pro",
        ),
    )

    api_key, base_url, model = content_writer_agent._get_llm_client_config()

    assert api_key == "sk-openrouter"
    assert base_url == "https://openrouter.ai/api/v1"
    assert model == "deepseek/deepseek-v4-pro"


def _fill_one(**kwargs):
    return content_writer_agent.fill_technical_volume(
        node_titles=["施工组织设计"],
        project_name="测试项目",
        requirements={},
        company_name="安徽正奇建设有限公司",
        **kwargs,
    )


def test_short_node_triggers_rewrite_and_keeps_longer(monkeypatch) -> None:
    long_text = "施工部署详尽措施。" * 200  # well above the 1200-char budget
    calls: list[str] = []

    def fake(messages, *, agent_name, continuation_instruction=""):
        calls.append(agent_name)
        return long_text if "deepen" in agent_name else "篇幅太短。"

    monkeypatch.setattr(content_writer_agent, "_generate_messages_with_llm", fake)

    res = _fill_one()
    node = res.nodes[0]
    assert any("deepen" in c for c in calls)  # rewrite was attempted
    assert node.short is False
    assert content_writer_agent._compact_len(node.content) >= content_writer_agent.MIN_NODE_CONTENT_CHARS


def test_node_still_short_after_rewrite_is_flagged(monkeypatch) -> None:
    monkeypatch.setattr(
        content_writer_agent,
        "_generate_messages_with_llm",
        lambda *a, **k: "依然太短的内容。",
    )
    res = _fill_one()
    assert res.nodes[0].short is True


def test_long_node_does_not_trigger_rewrite(monkeypatch) -> None:
    calls: list[str] = []

    def fake(messages, *, agent_name, continuation_instruction=""):
        calls.append(agent_name)
        return "充分详实的工程正文内容。" * 200

    monkeypatch.setattr(content_writer_agent, "_generate_messages_with_llm", fake)
    res = _fill_one()
    assert not any("deepen" in c for c in calls)
    assert res.nodes[0].short is False
