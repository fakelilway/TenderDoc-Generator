"""V2-M4 Content Writer Agent — per-node prose content generation.

Design principle: the skeleton's structure is immutable. LLM only writes
content under each prose-section heading. No heading manipulation, no
table generation, no form templates — just construction plan prose.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from core.config import get_settings
from core.llm_client import resolve_llm_config
from prompts.generator_prompt import build_node_fill_prompt

logger = logging.getLogger(__name__)

# Minimum compact (whitespace-stripped) character budget per technical node.
# A施工组织设计 section that falls below this is too thin to be competitive, so
# we rewrite it once with a deepen instruction before accepting it.
MIN_NODE_CONTENT_CHARS = 1200

_WS = re.compile(r"\s+")


def _compact_len(text: str) -> int:
    return len(_WS.sub("", text or ""))


@dataclass
class NodeFillResult:
    title: str
    content: str
    token_count: int = 0
    model_name: str = ""
    short: bool = False  # True if still below the length budget after one rewrite


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
    score_items: list[dict[str, Any]] | None = None,
    invalid_items: list[dict[str, Any]] | None = None,
    section_guidance: str = "",
    min_chars: int = 0,
) -> VolumeFillResult:
    """Fill all prose nodes in the technical volume.

    Each node gets a focused LLM call. Nodes are processed sequentially
    to respect rate limits; they are independent so future versions can
    parallelize via ThreadPoolExecutor.

    ``score_items`` / ``invalid_items`` are the relevant评分项/废标项 for these
    nodes; ``section_guidance`` is the canonical must-cover points for the
    section; ``min_chars`` is the per-section length target.
    """
    # Per-section length budget (canonical outline targets), else the default.
    target = min_chars or MIN_NODE_CONTENT_CHARS
    threshold = max(int(target * 0.75), MIN_NODE_CONTENT_CHARS)

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
            score_items=score_items,
            invalid_items=invalid_items,
            section_guidance=section_guidance,
            target_chars=target,
        )
        raw = _generate_messages_with_llm(
            messages,
            agent_name=f"content-writer-{title[:20]}",
            continuation_instruction="继续输出本节正文，从上次中断处继续。",
        )
        cleaned = _clean_node_content(raw, title)

        # Phase 1.3 — one rewrite when the node is below its length/depth budget.
        if _compact_len(cleaned) < threshold:
            cleaned = _rewrite_node_deeper(messages, cleaned, title, target)

        short = _compact_len(cleaned) < threshold
        if short:
            logger.warning(
                "Technical node '%s' still below budget after rewrite "
                "(%d < %d chars) — flagged for review, not silently accepted.",
                title, _compact_len(cleaned), threshold,
            )
        results.append(NodeFillResult(title=title, content=cleaned, short=short))
        previous_content = cleaned[:1200]  # context for next node (continuity)

    # Combine into one markdown per volume
    combined_parts = []
    for r in results:
        combined_parts.append(f"\n## {r.title}\n\n{r.content}\n")

    return VolumeFillResult(
        volume="technical",
        nodes=results,
        combined="\n".join(combined_parts),
    )


def _rewrite_node_deeper(
    base_messages: list[dict[str, str]], first_draft: str, title: str, target: int = 0
) -> str:
    """Rewrite a too-thin node once, deeper. Returns the longer of the two drafts.

    Sends the first draft back with a deepen instruction asking for a full
    rewrite (not a continuation) so the result is self-contained. Falls back to
    the first draft if the rewrite call fails or comes back shorter.
    """
    goal = target or MIN_NODE_CONTENT_CHARS
    deepen_messages = base_messages + [
        {"role": "assistant", "content": first_draft},
        {
            "role": "user",
            "content": (
                f"上文篇幅不足、工程深度不够。请重写本节“{title}”的完整正文，"
                f"在保留原有要点的前提下大幅扩充：补充具体工程参数与数据、"
                f"分步施工工艺、质量验收标准、安全与环保及应急措施、"
                f"人材机资源投入安排，并逐条正面响应评分点。"
                f"只输出本节正文，不少于 {goal} 字，"
                f"不得输出标题或元话语。"
            ),
        },
    ]
    try:
        raw = _generate_messages_with_llm(
            deepen_messages, agent_name=f"content-writer-deepen-{title[:16]}"
        )
    except Exception:
        logger.warning("Deepen rewrite failed for node '%s'; keeping first draft.", title, exc_info=True)
        return first_draft
    rewritten = _clean_node_content(raw, title)
    return rewritten if _compact_len(rewritten) > _compact_len(first_draft) else first_draft


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


def _get_llm_client_config() -> tuple[str, str, str]:
    return resolve_llm_config(get_settings())
