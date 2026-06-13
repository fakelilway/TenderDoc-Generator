"""V2-M4 Content Writer Agent — per-node prose content generation.

Design principle: the skeleton's structure is immutable. LLM only writes
content under each prose-section heading. No heading manipulation, no
table generation, no form templates — just construction plan prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from core.config import get_settings
from prompts.generator_prompt import build_node_fill_prompt


@dataclass
class NodeFillResult:
    title: str
    content: str
    token_count: int = 0
    model_name: str = ""


@dataclass
class VolumeFillResult:
    volume: str
    nodes: list[NodeFillResult] = field(default_factory=list)
    combined: str = ""

    @property
    def total_tokens(self) -> int:
        return sum(n.token_count for n in self.nodes)


def fill_technical_volume(
    *,
    node_titles: list[str],
    project_name: str,
    requirements: dict[str, Any],
    company_name: str,
    knowledge_chunks: list[dict[str, Any]] | None = None,
    tender_text: str = "",
) -> VolumeFillResult:
    """Fill all prose nodes in the technical volume.

    Each node gets a focused LLM call. Nodes are processed sequentially
    to respect rate limits; they are independent so future versions can
    parallelize via ThreadPoolExecutor.
    """
    results: list[NodeFillResult] = []
    previous_content: str = ""

    for title in node_titles:
        messages = build_node_fill_prompt(
            node_title=title,
            project_name=project_name,
            requirements=requirements,
            company_name=company_name,
            knowledge_chunks=knowledge_chunks,
            previous_node_content=previous_content,
            tender_text=tender_text,
        )
        raw = _generate_messages_with_llm(
            messages,
            agent_name=f"content-writer-{title[:20]}",
            continuation_instruction="继续输出本节正文，从上次中断处继续。",
        )

        cleaned = _clean_node_content(raw, title)
        results.append(NodeFillResult(title=title, content=cleaned))
        previous_content = cleaned[:300]  # brief context for next node

    # Combine into one markdown per volume
    combined_parts = []
    for r in results:
        combined_parts.append(f"\n## {r.title}\n\n{r.content}\n")

    return VolumeFillResult(
        volume="technical",
        nodes=results,
        combined="\n".join(combined_parts),
    )


def _clean_node_content(raw: str, title: str) -> str:
    """Strip any heading repeats, meta-text, or structure that LLM might add."""
    text = raw.strip()

    # Remove if LLM repeated the heading
    heading_patterns = [
        f"# {title}",
        f"## {title}",
        f"### {title}",
        f"# {title.lstrip('#').strip()}",
        f"## {title.lstrip('#').strip()}",
    ]
    for pattern in heading_patterns:
        if text.startswith(pattern):
            text = text[len(pattern) :].strip()

    # Remove AI meta-text
    bad_prefixes = [
        "好的，",
        "以下是为您",
        "这是",
        "根据您的要求",
        "以下是",
        "【待填写】",
        "待补充",
        "TODO",
        "（注：",
    ]
    for bp in bad_prefixes:
        if text.startswith(bp):
            # Try to find first sentence after the meta-text
            for sep in ["。\n", "。\n\n", "。"]:
                idx = text.find(sep)
                if idx > 10 and idx < 200:
                    text = text[idx + len(sep) :].strip()
                    break

    return text


def _generate_messages_with_llm(
    messages: list[dict[str, str]],
    *,
    agent_name: str,
    continuation_instruction: str = "",
) -> str:
    settings = get_settings()
    api_key, base_url, model = _get_llm_client_config()
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=settings.bid_long_context_max_tokens,
        timeout=settings.bid_long_context_timeout_seconds,
    )
    if not response.choices:
        raise RuntimeError(f"{agent_name} response did not contain choices")
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise RuntimeError(f"{agent_name} response was empty")
    return content


def _has_real_key(value: str) -> bool:
    return bool(value and value.strip() and "xxxx" not in value.lower())


def _get_llm_client_config() -> tuple[str, str, str]:
    settings = get_settings()
    provider = str(getattr(settings, "bid_llm_provider", "auto") or "auto").lower()
    if provider == "deepseek":
        if _has_real_key(settings.deepseek_api_key):
            return (
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
            )
        raise RuntimeError(
            "DEEPSEEK_API_KEY is required when BID_LLM_PROVIDER=deepseek"
        )
    if provider == "openrouter":
        if _has_real_key(settings.openrouter_api_key):
            return (
                settings.openrouter_api_key,
                settings.openrouter_base_url,
                settings.openrouter_model,
            )
        raise RuntimeError(
            "OPENROUTER_API_KEY is required when BID_LLM_PROVIDER=openrouter"
        )
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
    raise RuntimeError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")
