import threading
from types import SimpleNamespace

import pytest

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


_LONG = "充分详实的工程正文内容。" * 200  # above budget → no deepen rewrite


def test_nodes_run_concurrently_and_reassemble_in_order(monkeypatch) -> None:
    titles = [f"第{i}节" for i in range(4)]
    # A 4-party barrier only releases if all 4 node calls are in flight at once;
    # if the pool serialized them, the first wait would time out (BrokenBarrier).
    barrier = threading.Barrier(4, timeout=5)

    def fake(messages, *, agent_name, continuation_instruction=""):
        barrier.wait()
        return _LONG

    monkeypatch.setattr(content_writer_agent, "_generate_messages_with_llm", fake)

    res = content_writer_agent.fill_technical_volume(
        node_titles=titles,
        project_name="P",
        requirements={},
        company_name="C",
        max_workers=4,
    )

    # Concurrency proven (no BrokenBarrierError) and results kept in node order.
    assert [n.title for n in res.nodes] == titles


def test_one_node_failure_is_isolated_and_aggregated(monkeypatch) -> None:
    titles = ["好节点A", "坏节点B", "好节点C"]
    seen: list[str] = []
    lock = threading.Lock()

    def fake(messages, *, agent_name, continuation_instruction=""):
        with lock:
            seen.append(agent_name)
        if "坏节点B" in agent_name:
            raise RuntimeError("boom")
        return _LONG

    monkeypatch.setattr(content_writer_agent, "_generate_messages_with_llm", fake)

    with pytest.raises(RuntimeError, match="坏节点B"):
        content_writer_agent.fill_technical_volume(
            node_titles=titles,
            project_name="P",
            requirements={},
            company_name="C",
            max_workers=3,
        )

    # The failing node did not cancel its siblings — both good nodes still ran.
    assert any("好节点A" in s for s in seen)
    assert any("好节点C" in s for s in seen)


def test_per_title_overrides_route_to_each_node(monkeypatch) -> None:
    titles = ["质量管理", "安全文明"]
    captured: dict[str, str] = {}

    def fake(messages, *, agent_name, continuation_instruction=""):
        user = next(m["content"] for m in messages if m["role"] == "user")
        # agent_name is content-writer-<title[:20]>; key by the title fragment.
        title = agent_name.replace("content-writer-", "")
        captured[title] = user
        return _LONG

    monkeypatch.setattr(content_writer_agent, "_generate_messages_with_llm", fake)

    content_writer_agent.fill_technical_volume(
        node_titles=titles,
        project_name="P",
        requirements={},
        company_name="C",
        guidance_by_title={"质量管理": "三检制要点", "安全文明": "安全网封闭"},
        max_workers=2,
    )

    assert "三检制要点" in captured["质量管理"]
    assert "安全网封闭" in captured["安全文明"]
    # guidance is not cross-contaminated between sections
    assert "安全网封闭" not in captured["质量管理"]
