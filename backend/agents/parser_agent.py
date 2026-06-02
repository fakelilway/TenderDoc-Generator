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


RELEVANT_KEYWORDS = (
    "项目名称",
    "工程名称",
    "招标项目名称",
    "投标人资格",
    "资格要求",
    "资格审查",
    "资质",
    "安全生产许可证",
    "项目经理",
    "项目总工",
    "评分",
    "评分因素",
    "评分标准",
    "技术评分",
    "施工组织设计",
    "评标办法",
    "否决",
    "废标",
    "无效投标",
    "重大偏差",
)


def _has_real_key(value: str) -> bool:
    return bool(value and value.strip() and "xxxx" not in value.lower())


def _get_llm_client_config() -> tuple[str, str, str]:
    settings = get_settings()
    if _has_real_key(settings.openrouter_api_key):
        return (
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
        )
    if _has_real_key(settings.deepseek_api_key):
        return (
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    raise ParserAgentError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")


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


def _prepare_tender_text(text: str, max_chars: int = 45000) -> str:
    """Keep the LLM input focused on parser-relevant tender sections."""
    if len(text) <= max_chars:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected_indexes: list[int] = []
    seen: set[int] = set()

    def add_index(index: int) -> None:
        if index not in seen:
            selected_indexes.append(index)
            seen.add(index)

    for index, _line in enumerate(lines[:40]):
        add_index(index)

    for index, line in enumerate(lines):
        if any(keyword in line for keyword in RELEVANT_KEYWORDS):
            start = max(0, index - 4)
            end = min(len(lines), index + 12)
            for selected_index in range(start, end):
                add_index(selected_index)

    focused_lines: list[str] = []
    current_length = 0
    for index in selected_indexes:
        line = lines[index]
        next_length = current_length + len(line) + 1
        if next_length > max_chars:
            continue
        focused_lines.append(line)
        current_length = next_length

    return "\n".join(focused_lines)


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
    """Extract tender requirements with the configured OpenAI-compatible LLM."""
    if not text.strip():
        raise ValueError("Tender text is empty")
    api_key, base_url, model = _get_llm_client_config()
    tender_text = _prepare_tender_text(text)

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=build_parser_prompt(tender_text),
        temperature=0,
        max_tokens=3000,
        response_format={"type": "json_object"},
    )

    if not response.choices:
        raise ParserAgentError(
            f"LLM response did not contain choices: {response.model_dump_json()[:1000]}"
        )
    content = response.choices[0].message.content or ""
    return parse_tender_response(content)
