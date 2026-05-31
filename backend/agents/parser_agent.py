from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from core.config import get_settings
from prompts.parser_prompt import build_parser_prompt
from schemas.tender import TenderRequirements


class ParserAgentError(RuntimeError):
    pass


def _strip_markdown_fence(content: str) -> str:
    content = content.strip()
    fence_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE
    )
    if fence_match:
        return fence_match.group(1).strip()
    return content


def _extract_json_object(content: str) -> str:
    content = _strip_markdown_fence(content)
    if content.startswith("{") and content.endswith("}"):
        return content

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ParserAgentError("LLM response did not contain a JSON object")
    return content[start : end + 1]


def _remove_trailing_commas(content: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", content)


def parse_tender_response(content: str) -> TenderRequirements:
    """Parse and validate raw LLM output into the MVP tender schema."""
    json_text = _remove_trailing_commas(_extract_json_object(content))
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ParserAgentError(f"Failed to decode parser JSON: {exc}") from exc

    try:
        return TenderRequirements.model_validate(data)
    except ValidationError as exc:
        raise ParserAgentError(
            f"Parser JSON did not match TenderRequirements: {exc}"
        ) from exc


def parse_tender(text: str) -> TenderRequirements:
    """Extract tender requirements with the configured DeepSeek-compatible LLM."""
    if not text.strip():
        raise ValueError("Tender text is empty")
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise ParserAgentError("DEEPSEEK_API_KEY is required to parse tender text")

    client = OpenAI(
        api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url
    )
    response = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=build_parser_prompt(text),
        temperature=0,
        max_tokens=3000,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or ""
    return parse_tender_response(content)
