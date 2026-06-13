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
