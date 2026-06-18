"""商务文件「通读整本招标 → LLM 生成商务响应」服务。

四块:① 资格审查响应 ② 商务条款偏离表 ③ 声明与承诺 ④ 投标函关键值一致性。
产物是 Markdown,直接 append 进商务卷 commercial_md,由 _render_markdown_body 渲染进 docx。

设计契约:
- **整本招标喂进去**:用户用 DeepSeek 1M 上下文、不计 token,招标全文不做小截断(仅设极高安全上限防异常超大文本)。
- **best-effort 不阻断**:招标全文缺失 / LLM 失败 / 空返回 → 返回 "",商务卷照常出,绝不把整卷生成搞崩。
- LLM 调用复用 core/llm_client(resolve_llm_config + chat_completion),长上下文预算复用 settings.bid_long_context_*。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from openai import OpenAI

from core.config import get_settings
from core.llm_client import chat_completion, resolve_llm_config
from prompts.commercial_response_prompt import build_commercial_response_prompt

logger = logging.getLogger(__name__)

# 招标全文整本喂(DeepSeek 1M)。仅设极高安全上限防异常超大输入,正常招标(约9万字)不受影响。
_TENDER_TEXT_CEILING = 300_000


def _default_complete(messages: list[dict[str, str]]) -> str:
    """标准 LLM 入口:resolve_llm_config → OpenAI client → chat_completion(带瞬时重试)。"""
    settings = get_settings()
    api_key, base_url, model = resolve_llm_config(settings)
    client = OpenAI(api_key=api_key, base_url=base_url)
    # 长输出预算复用技术卷长文那对参数;max_tokens 控在 32000 足够四块响应,且两家供应商都安全。
    max_tokens = min(
        int(getattr(settings, "bid_long_context_max_tokens", 100000) or 100000),
        32000,
    )
    timeout = int(getattr(settings, "bid_long_context_timeout_seconds", 300) or 300)
    response = chat_completion(
        client,
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def generate_commercial_responses(
    requirements: Any,
    tender_text: str,
    profile: dict[str, str] | None = None,
    *,
    complete: Callable[[list[dict[str, str]]], str] | None = None,
) -> str:
    """通读整本招标 → 生成四块商务响应 Markdown(含附录标题与定位声明)。

    失败 / 无招标全文 / 空返回 → 返回 ""(调用方据此回退到模板浅响应)。
    """
    text = (tender_text or "").strip()
    if not text:
        return ""
    if len(text) > _TENDER_TEXT_CEILING:
        text = text[:_TENDER_TEXT_CEILING]

    completer = complete or _default_complete
    try:
        req = (
            requirements.model_dump()
            if hasattr(requirements, "model_dump")
            else dict(requirements or {})
        )
        messages = build_commercial_response_prompt(
            requirements=req,
            tender_text=text,
            profile=profile or {},
        )
        body = (completer(messages) or "").strip()
    except Exception:
        logger.warning("商务响应生成失败,回退模板浅响应(不阻断出标)", exc_info=True)
        return ""

    if not body:
        return ""

    header = (
        "\n<!-- tdg:pagebreak -->\n"
        "\n## 附录：商务响应（AI 通读招标文件生成，供编制参考；"
        "非招标文件格式原文，正式商务表以上方原格式页为准）\n"
        "\n> 以下内容由系统通读整本招标文件后逐条生成；涉及金额／报价均留 ________ 由人工确认。\n"
    )
    return f"{header}\n{body}\n"
