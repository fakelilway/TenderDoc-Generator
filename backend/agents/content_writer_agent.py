"""V2-M4 Content Writer Agent — per-node prose content generation.

Design principle: the skeleton's structure is immutable. LLM only writes
content under each prose-section heading. No heading manipulation, no
table generation, no form templates — just construction plan prose.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from core.config import get_settings
from core.llm_client import chat_completion, resolve_llm_config
from prompts.generator_prompt import build_node_fill_prompt

logger = logging.getLogger(__name__)

# Minimum compact (whitespace-stripped) character budget per technical node.
# A施工组织设计 section that falls below this is too thin to be competitive, so
# we rewrite it once with a deepen instruction before accepting it.
MIN_NODE_CONTENT_CHARS = 1200

# Default bounded fan-out for the per-node LLM calls. Each node is independent,
# so we generate several at once; the cap keeps us under the provider rate limit.
DEFAULT_WRITER_CONCURRENCY = 5

# Full re-attempts per node before it counts as failed. A transient LLM blip
# (429/timeout/empty) on ONE node under concurrency must not fail the whole
# volume — most clear on a fresh attempt. (This is on top of core.llm_client's
# in-call transient retries.) Only if ALL attempts fail do we surface it.
NODE_MAX_ATTEMPTS = 3

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
    score_items_by_title: dict[str, list[dict[str, Any]]] | None = None,
    invalid_items_by_title: dict[str, list[dict[str, Any]]] | None = None,
    guidance_by_title: dict[str, str] | None = None,
    min_chars_by_title: dict[str, int] | None = None,
    max_workers: int = DEFAULT_WRITER_CONCURRENCY,
) -> VolumeFillResult:
    """Fill all prose nodes in the technical volume with bounded concurrency.

    Each node gets a focused, independent LLM call. The same ``requirements`` are
    injected into every node's prompt so工期/质量·安全目标/工程量 stay consistent
    across sections, while the prompt itself instructs each node to write only its
    own topic (no工程概况复述, no cross-section duplication) — so we deliberately
    drop the old adjacent-node continuity, which does not matter for a bid and
    blocked parallelism.

    Nodes run through a :class:`ThreadPoolExecutor` capped at ``max_workers`` to
    cut the ~25-section volume from ~25 min to ~5-6 min; the cap keeps us under
    the provider's rate limit and transient 429s are retried in ``core.llm_client``.
    Results are reassembled in ``node_titles`` order, and one node's failure is
    aggregated and re-raised *after* the others finish rather than cancelling them.

    Per-node overrides (``*_by_title``) let a caller pass each section its own
    评分项/废标项/must-cover/length budget; the scalar ``score_items`` /
    ``invalid_items`` / ``section_guidance`` / ``min_chars`` remain as shared
    fallbacks for single-node callers.
    """
    score_by_title = score_items_by_title or {}
    invalid_by_title = invalid_items_by_title or {}
    guidance_map = guidance_by_title or {}
    min_chars_map = min_chars_by_title or {}

    def _fill_node(title: str) -> NodeFillResult:
        # Per-section length budget (canonical outline targets), else the default.
        node_min = min_chars_map.get(title, min_chars)
        target = node_min or MIN_NODE_CONTENT_CHARS
        threshold = max(int(target * 0.75), MIN_NODE_CONTENT_CHARS)

        messages = build_node_fill_prompt(
            node_title=title,
            project_name=project_name,
            requirements=requirements,
            company_name=company_name,
            knowledge_chunks=knowledge_chunks,
            tender_text=tender_text,
            score_items=score_by_title.get(title, score_items),
            invalid_items=invalid_by_title.get(title, invalid_items),
            section_guidance=guidance_map.get(title, section_guidance),
            target_chars=target,
        )
        # 每节多次完整尝试:并发下某节偶发 429/超时/空返回,不该拖垮整卷;多数重试即过。
        # 全部尝试都失败才上抛(由调用方聚合、按铁律失败,不输出占位)。
        last_exc: Exception | None = None
        for attempt in range(1, NODE_MAX_ATTEMPTS + 1):
            try:
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
                return NodeFillResult(title=title, content=cleaned, short=short)
            except Exception as exc:  # noqa: BLE001 - retried; re-raised after all attempts
                last_exc = exc
                logger.warning(
                    "Technical node '%s' attempt %d/%d failed: %s",
                    title, attempt, NODE_MAX_ATTEMPTS, exc,
                )
                if attempt < NODE_MAX_ATTEMPTS:
                    time.sleep(min(2 ** attempt, 10))
        raise last_exc  # all attempts failed → caller aggregates & fails loud

    # Reassembled in node order; failures collected so one bad node does not
    # cancel siblings (no silent placeholder prose — we raise once all settle).
    results: list[NodeFillResult | None] = [None] * len(node_titles)
    errors: list[tuple[str, BaseException]] = []
    workers = max(1, min(max_workers, len(node_titles)))

    if workers == 1:
        for idx, title in enumerate(node_titles):
            try:
                results[idx] = _fill_node(title)
            except Exception as exc:  # noqa: BLE001 - aggregated and re-raised below
                logger.error("Technical node '%s' failed", title, exc_info=True)
                errors.append((title, exc))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(_fill_node, title): idx
                for idx, title in enumerate(node_titles)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001 - aggregated and re-raised below
                    logger.error(
                        "Technical node '%s' failed", node_titles[idx], exc_info=True
                    )
                    errors.append((node_titles[idx], exc))

    if errors:
        failed = "、".join(title for title, _ in errors)
        raise RuntimeError(
            f"技术正文生成失败的节点（{len(errors)}/{len(node_titles)}）：{failed}"
        ) from errors[0][1]

    final_nodes = [r for r in results if r is not None]
    combined_parts = [f"\n## {r.title}\n\n{r.content}\n" for r in final_nodes]
    return VolumeFillResult(
        volume="technical",
        nodes=final_nodes,
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
    response = chat_completion(
        client,
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
