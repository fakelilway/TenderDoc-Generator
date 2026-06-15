"""Shared LLM provider resolution for bid-generation agents.

Historically ``parser_agent`` and ``content_writer_agent`` each carried a
byte-for-byte copy of the provider-selection logic, differing only in the
exception type they raised.  Centralising it here keeps provider/key handling in
one place so model switches, key validation and (later) retry policy only need
to change once.

The exception type is injectable via ``error_cls`` precisely because the parser
must keep raising ``ParserAgentError`` (its tests assert on it) while other
callers default to ``RuntimeError``.

Note: ``reviewer_agent`` intentionally keeps its own inline selection policy
(prefer OpenRouter, ignore ``BID_LLM_PROVIDER``, return no findings when no key
is configured).  That is a different behaviour, not a duplicate, so it is *not*
consolidated here.
"""

from __future__ import annotations

from openai import OpenAI

from core.config import get_settings


def has_real_key(value: str) -> bool:
    """True when ``value`` looks like a configured key rather than a placeholder."""
    return bool(value and value.strip() and "xxxx" not in value.lower())


def resolve_llm_config(
    settings: object | None = None,
    *,
    error_cls: type[Exception] = RuntimeError,
) -> tuple[str, str, str]:
    """Resolve ``(api_key, base_url, model)`` for the configured LLM provider.

    Honours ``BID_LLM_PROVIDER`` (``deepseek`` / ``openrouter``); ``auto`` (the
    default) prefers OpenRouter and falls back to DeepSeek.  Raises ``error_cls``
    when the required key is missing so callers can surface their own error type.

    Callers pass their own ``settings`` (resolved via the caller module's
    ``get_settings``) so existing per-agent ``monkeypatch`` of ``get_settings``
    keeps working; when omitted it falls back to this module's ``get_settings``.
    """
    if settings is None:
        settings = get_settings()
    provider = str(getattr(settings, "bid_llm_provider", "auto") or "auto").lower()
    if provider == "deepseek":
        if has_real_key(settings.deepseek_api_key):
            return (
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
            )
        raise error_cls("DEEPSEEK_API_KEY is required when BID_LLM_PROVIDER=deepseek")
    if provider == "openrouter":
        if has_real_key(settings.openrouter_api_key):
            return (
                settings.openrouter_api_key,
                settings.openrouter_base_url,
                settings.openrouter_model,
            )
        raise error_cls("OPENROUTER_API_KEY is required when BID_LLM_PROVIDER=openrouter")
    if has_real_key(settings.openrouter_api_key):
        return (
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
        )
    if has_real_key(settings.deepseek_api_key):
        return (
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    raise error_cls("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")


def build_client(api_key: str, base_url: str, *, timeout: float | None = None) -> OpenAI:
    """Construct an OpenAI-compatible client, passing ``timeout`` only when set."""
    if timeout is not None:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    return OpenAI(api_key=api_key, base_url=base_url)
