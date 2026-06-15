"""Tests for the transient-error retry wrapper in ``core.llm_client``.

These exercise :func:`core.llm_client.chat_completion`:
  (a) transient errors are retried and a later success is returned;
  (b) retries are bounded by ``max_attempts`` and the last error propagates;
  (c) deterministic 4xx errors are never retried.

All tests inject ``sleep=lambda *_: None`` so the exponential backoff never
sleeps for real wall-clock time.
"""

from __future__ import annotations

import httpx
import openai
import pytest

from core.llm_client import chat_completion


class _FakeCompletions:
    """Stand-in for ``client.chat.completions`` with scripted ``create``.

    ``script`` is a list of items returned/raised in order: an ``Exception``
    instance is raised, anything else is returned. Records the number of calls.
    """

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, script: list[object]) -> None:
        self.chat = _FakeChat(_FakeCompletions(script))


def _timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "http://test"))


def _bad_request_error() -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    return openai.BadRequestError("bad request", response=response, body=None)


class _SleepSpy:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def test_retries_transient_then_succeeds() -> None:
    """(a) Two timeouts then success: returns result, sleeps twice (1s, 2s)."""
    sentinel = object()
    client = _FakeClient([_timeout_error(), _timeout_error(), sentinel])
    sleep = _SleepSpy()

    result = chat_completion(client, max_attempts=3, base_delay=1.0, sleep=sleep, model="m")

    assert result is sentinel
    assert client.chat.completions.calls == 3
    assert sleep.delays == [1.0, 2.0]


def test_retries_exhausted_raises_last_transient_error() -> None:
    """(b) Always timing out: raises APITimeoutError once attempts run out."""
    client = _FakeClient([_timeout_error(), _timeout_error(), _timeout_error()])
    sleep = _SleepSpy()

    with pytest.raises(openai.APITimeoutError):
        chat_completion(client, max_attempts=3, base_delay=1.0, sleep=sleep, model="m")

    assert client.chat.completions.calls == 3
    # One sleep between each of the 3 attempts except the last -> 2 sleeps.
    assert sleep.delays == [1.0, 2.0]


def test_non_transient_4xx_not_retried() -> None:
    """(c) BadRequestError (4xx) is raised immediately, no sleep."""
    client = _FakeClient([_bad_request_error()])
    sleep = _SleepSpy()

    with pytest.raises(openai.BadRequestError):
        chat_completion(client, max_attempts=3, base_delay=1.0, sleep=sleep, model="m")

    assert client.chat.completions.calls == 1
    assert sleep.delays == []
