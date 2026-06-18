"""抽招标第三章「评标办法」→ 结构化评审标准,并转成逐空核对项。

目的(回应业务方质疑):审查标准必须来自招标真实「评审因素与评审标准」,而非代码写死的通用规则。
本服务:① 定位评标办法那几页 → ② LLM 逐条照抄成 TenderReviewMethod → ③ 转成 FillRequirement
追加进核对报告(带真实条款号出处)。**自包含**(不 import tender_spec_service,避免循环依赖)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from prompts.review_method_prompt import build_review_method_prompt
from schemas.tender_spec import (
    FillRequirement,
    RejectionRule,
    ReviewCriterion,
    ScoreItem,
    TenderReviewMethod,
)

logger = logging.getLogger(__name__)

# 整本喂(DeepSeek 1M、不计 token):评标办法章可能很长(评审表+评分细则+否决条款逐条),
# 旧 40000 截断会切掉后半;设高上限,确保定位到的评标办法整章都进窗口。
_REVIEW_TEXT_CAP = 200000

Completion = Callable[[list[dict[str, str]]], str]


def _default_complete(messages: list[dict[str, str]]) -> str:
    from openai import OpenAI

    from agents.parser_agent import _get_llm_client_config
    from core.config import get_settings
    from core.llm_client import chat_completion

    settings = get_settings()
    api_key, base_url, model = _get_llm_client_config()
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = chat_completion(
        client,
        model=model,
        messages=messages,
        temperature=0.1,
        # 评标办法逐条照抄原文,输出量大;整本喂后条目更多,输出预算调大防 JSON 截断
        # (8000 仍偶被截、靠 salvage 兜底);长输入用长超时。
        max_tokens=16000,
        timeout=float(
            getattr(settings, "bid_long_context_timeout_seconds", 300)
            or getattr(settings, "parser_llm_timeout_seconds", 120.0)
        ),
    )
    return response.choices[0].message.content or ""


def _salvage_truncated_json(text: str) -> dict[str, Any]:
    """LLM 输出被 max_tokens 截断时,从尾部回退到最后一个完整对象,补齐括号抢救出已抽到的条目。"""
    start = text.find("{")
    if start < 0:
        return {}
    body = text[start:]
    # 从最后一个 '}' 往前逐个尝试:截到该处 + 补齐未闭合的 ] 和 }
    close_positions = [i for i, ch in enumerate(body) if ch == "}"]
    for pos in reversed(close_positions):
        frag = body[: pos + 1].rstrip().rstrip(",")
        opens = frag.count("{") - frag.count("}")
        obrk = frag.count("[") - frag.count("]")
        candidate = frag + "]" * max(0, obrk) + "}" * max(0, opens)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and any(
                data.get(k) for k in ("criteria", "score_items", "rejection_rules")
            ):
                return data
        except Exception:
            continue
    return {}


def _parse_json(raw: str) -> dict[str, Any]:
    from agents.parser_agent import (
        _extract_json_object,
        _remove_trailing_commas,
        _strip_markdown_fence,
    )

    cleaned_raw = _strip_markdown_fence(raw)
    try:
        cleaned = _remove_trailing_commas(_extract_json_object(cleaned_raw))
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        # 多半是被截断的半截 JSON → 抢救出已完整的条目,而不是整盘返回空。
        salvaged = _salvage_truncated_json(cleaned_raw)
        if salvaged:
            logger.warning("评标办法 JSON 疑似截断,已抢救出部分条目")
            return salvaged
        logger.warning("评标办法 JSON 解析失败,返回空", exc_info=True)
        return {}


def locate_review_method_text(tender_text: str, *, cap: int = _REVIEW_TEXT_CAP) -> str:
    """定位「评标办法」章节正文(避开目录幻影,取正文那段)。"""
    if not (tender_text or "").strip():
        return ""
    # 取"第N章 评标办法"的**最后一次**出现(目录在前,正文在后)
    chapter_hits = list(re.finditer(r"第[一二三四五六七八九十百\d]+章\s*评标办法", tender_text))
    if chapter_hits:
        start = chapter_hits[-1].start()
        nxt = re.search(r"第[一二三四五六七八九十百\d]+章\s", tender_text[start + 10:])
        end = start + 10 + (nxt.start() if nxt else cap)
        return tender_text[start:end][:cap]
    # 兜底:从评标办法本体的标志词处开窗
    for kw in ("评标办法前附表", "评审因素与评审标准", "初步评审标准", "评审标准"):
        i = tender_text.rfind(kw)
        if i != -1:
            return tender_text[i : i + cap]
    return ""


def _to_review_method(data: dict[str, Any]) -> TenderReviewMethod:
    """LLM dict → TenderReviewMethod,脏字段不炸、丢弃即可。"""

    def _f(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    criteria: list[ReviewCriterion] = []
    for row in data.get("criteria") or []:
        if isinstance(row, dict) and (row.get("standard") or row.get("factor")):
            criteria.append(
                ReviewCriterion(
                    category=str(row.get("category", "") or ""),
                    clause_no=str(row.get("clause_no", "") or ""),
                    factor=str(row.get("factor", "") or ""),
                    standard=str(row.get("standard", "") or ""),
                    is_reject=bool(row.get("is_reject", False)),
                )
            )

    score_items: list[ScoreItem] = []
    for row in data.get("score_items") or []:
        if isinstance(row, dict) and (row.get("factor") or row.get("rule")):
            score_items.append(
                ScoreItem(
                    clause_no=str(row.get("clause_no", "") or ""),
                    factor=str(row.get("factor", "") or ""),
                    max_score=_f(row.get("max_score")),
                    rule=str(row.get("rule", "") or ""),
                )
            )

    rejection_rules: list[RejectionRule] = []
    for row in data.get("rejection_rules") or []:
        if isinstance(row, dict) and row.get("rule"):
            rejection_rules.append(
                RejectionRule(
                    clause_no=str(row.get("clause_no", "") or ""),
                    rule=str(row.get("rule", "") or ""),
                )
            )

    return TenderReviewMethod(
        method_name=str(data.get("method_name", "") or ""),
        total_score=_f(data.get("total_score")),
        criteria=criteria,
        score_items=score_items,
        rejection_rules=rejection_rules,
    )


def build_review_method(
    tender_text: str, *, complete: Completion | None = None
) -> TenderReviewMethod:
    """抽招标评标办法 → 结构化评审标准。抽不到/失败返回空(不阻断)。"""
    text = locate_review_method_text(tender_text)
    if not text.strip():
        return TenderReviewMethod()
    try:
        raw = (complete or _default_complete)(build_review_method_prompt(text))
        return _to_review_method(_parse_json(raw))
    except Exception:
        logger.warning("评标办法抽取失败,返回空(不阻断核对报告)", exc_info=True)
        return TenderReviewMethod()


def review_method_to_requirements(rm: TenderReviewMethod) -> list[FillRequirement]:
    """把招标评审标准转成核对项(逐条带真实条款号出处,status=待人工 供人工逐条核标书)。"""
    items: list[FillRequirement] = []
    for c in rm.criteria:
        items.append(
            FillRequirement(
                field=c.factor or "评审因素",
                source=c.clause_no or "第三章评标办法",
                required=c.standard,
                our_value="",
                status="待人工",
                action="告警",
                note=(
                    f"招标{c.category or '评审'}标准"
                    + ("(不符合即否决)" if c.is_reject else "")
                    + "；需人工核对标书是否满足"
                ),
            )
        )
    for s in rm.score_items:
        prefix = f"满分{s.max_score:g}分 " if s.max_score else ""
        items.append(
            FillRequirement(
                field=f"评分项：{s.factor}" if s.factor else "评分项",
                source=s.clause_no or "第三章评标办法",
                required=(prefix + (s.rule or "")).strip(),
                status="待人工",
                action="告警",
                note="招标评分细则；核对标书在此项是否充分响应、争取拿分",
            )
        )
    for r in rm.rejection_rules:
        items.append(
            FillRequirement(
                field="否决情形",
                source=r.clause_no or "第三章评标办法",
                required=r.rule,
                status="待人工",
                action="告警",
                note="招标否决投标情形；务必确认标书不触发",
            )
        )
    return items
