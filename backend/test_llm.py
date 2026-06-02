from openai import OpenAI

from agents.parser_agent import _has_real_key
from core.config import settings


def _get_smoke_llm_config() -> tuple[str, str, str, str]:
    if _has_real_key(settings.openrouter_api_key):
        return (
            "OpenRouter",
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
        )
    if _has_real_key(settings.deepseek_api_key):
        return (
            "DeepSeek",
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    raise RuntimeError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")


def main() -> None:
    try:
        provider, api_key, base_url, model = _get_smoke_llm_config()
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请回复 OK"}],
            max_tokens=10,
        )
        print(
            f"✓ 大模型 API 调用成功 ({provider}/{model}):",
            response.choices[0].message.content,
        )
    except Exception as exc:
        print(f"✗ 大模型 API 调用失败: {exc}")


if __name__ == "__main__":
    main()
