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

import time
from typing import Any, Callable

import openai
from openai import OpenAI

from core.config import get_settings


# Transient failures worth retrying: the request may succeed if simply re-sent.
# - APITimeoutError / APIConnectionError: network blip or slow upstream.
# - RateLimitError: provider asked us to back off (429); a short wait clears it.
# - InternalServerError: provider-side 5xx.
# Generic ``APIStatusError`` is handled separately below so we can retry *any*
# 5xx (e.g. 502/503/504 from a proxy) while still letting 4xx fall through.
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


def _is_transient(error: Exception) -> bool:
    """Return True only for errors a retry could plausibly fix.

    4xx errors (``BadRequestError``, ``AuthenticationError``,
    ``PermissionDeniedError``, ``NotFoundError``, ...) are deterministic client
    mistakes: re-sending the identical request will fail identically, so they
    are *not* transient and must propagate immediately. We treat a generic
    ``APIStatusError`` as transient only when its ``status_code`` is >= 500.
    """
    if isinstance(error, _RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(error, openai.APIStatusError):
        status_code = getattr(error, "status_code", None)
        return status_code is not None and status_code >= 500
    return False


def chat_completion(
    client: OpenAI,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], Any] = time.sleep,
    **kwargs: Any,
) -> Any:
    """Call ``client.chat.completions.create`` with transient-error retries.

    Wraps a single chat-completion request in a retry loop that uses
    exponential backoff. Only *transient* failures are retried (see
    :func:`_is_transient`): timeouts, rate limits, connection drops and 5xx
    responses, because those can clear on a re-send. Deterministic 4xx errors
    (bad request, auth, permission, not-found) are re-raised on the first
    occurrence — retrying them would only waste time and quota and never
    succeed.

    Backoff: after the n-th failed attempt (1-indexed) we ``sleep(base_delay *
    2 ** (n - 1))`` before the next attempt — i.e. 1s, 2s, 4s, ... for the
    default ``base_delay=1.0``. Once ``max_attempts`` is exhausted the last
    transient exception is re-raised *unwrapped* so callers see the original
    OpenAI error type (some agents branch on it / log it verbatim).

    ``sleep`` is injectable purely so tests can pass ``lambda *_: None`` and
    avoid real wall-clock delays; production code uses the default
    ``time.sleep``. All other keyword arguments (``model``, ``messages``,
    ``temperature``, ``max_tokens``, ``response_format``, ``timeout``, ...) are
    forwarded verbatim to ``create``.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as error:  # noqa: BLE001 - re-raised below
            if not _is_transient(error):
                raise
            last_error = error
            if attempt >= max_attempts:
                raise
            sleep(base_delay * 2 ** (attempt - 1))
    # Defensive: the loop always returns or raises above. Re-raise to satisfy
    # type-checkers and guard against an unexpected fall-through.
    assert last_error is not None  # pragma: no cover
    raise last_error  # pragma: no cover


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
    if provider == "kimi":
        if has_real_key(settings.kimi_api_key):
            return (
                settings.kimi_api_key,
                settings.kimi_base_url,
                settings.kimi_model,
            )
        raise error_cls("KIMI_API_KEY is required when BID_LLM_PROVIDER=kimi")
    if provider == "volcano":
        if has_real_key(settings.volcano_api_key):
            return (
                settings.volcano_api_key,
                settings.volcano_base_url,
                settings.volcano_model,
            )
        raise error_cls("VOLCANO_API_KEY is required when BID_LLM_PROVIDER=volcano")
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

