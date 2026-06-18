"""抽招标第五章「工程量清单」→ 分部分项大类+占总造价比重(TenderBOQ),并提供
"按占比定详略 + 把工程量喂给对应施工方案"的接线助手。

照搬 review_method_service 的稳妥模式:定位章节→整本喂→LLM 抽结构化→JSON 截断救援→
抽不到返回空不阻断。LLM 调用复用 core/llm_client(现走 OpenRouter Claude Opus 4.8,调用层零改动)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from prompts.boq_prompt import build_boq_prompt
from schemas.tender_spec import BOQCategory, TenderBOQ

logger = logging.getLogger(__name__)

# 整本喂:工程量清单(第五章)往往在招标 8 万字处且很长,设高上限确保整章进窗口。
_BOQ_TEXT_CAP = 200000
# 主导项阈值:占总造价 ≥ 25% 即视为主导分部分项,技术卷应重点详写。
_DOMINANT_SHARE = 25.0

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
        max_tokens=16000,
        timeout=float(
            getattr(settings, "bid_long_context_timeout_seconds", 300)
            or getattr(settings, "parser_llm_timeout_seconds", 120.0)
        ),
    )
    return response.choices[0].message.content or ""


def _salvage_truncated_json(text: str) -> dict[str, Any]:
    """LLM 输出被 max_tokens 截断时,从尾部回退到最后一个完整对象,补齐括号抢救已抽到的条目。"""
    start = text.find("{")
    if start < 0:
        return {}
    body = text[start:]
    for pos in reversed([i for i, ch in enumerate(body) if ch == "}"]):
        frag = body[: pos + 1].rstrip().rstrip(",")
        opens = frag.count("{") - frag.count("}")
        obrk = frag.count("[") - frag.count("]")
        candidate = frag + "]" * max(0, obrk) + "}" * max(0, opens)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and data.get("categories"):
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
        salvaged = _salvage_truncated_json(cleaned_raw)
        if salvaged:
            logger.warning("工程量清单 JSON 疑似截断,已抢救出部分条目")
            return salvaged
        logger.warning("工程量清单 JSON 解析失败,返回空", exc_info=True)
        return {}


# 匹配「第X章 工程量清单」,但用负向前瞻排除「工程量清单计量规则」(那是另册的计量规则章,非清单本体)。
_BOQ_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百\d]+章\s*工程量清单(?!\s*计量规则)")
# 真实工程量信号词:据此判断章节段是否含真清单(数量/单位/单价);很多招标的清单数量在另册,
# 章节段只剩"说明"——此时补入"分项工程列项"区域,让 LLM 至少据列项估占比。
_BOQ_SIGNAL = re.compile(r"(m³|m3|m²|m2|吨|km|立方米|平方米|工程数量|综合单价|清单编码|项目编码)")
_BOQ_LIST_KW = ("分项工程进度率", "分项工程", "工程数量表", "施工总体计划表", "主要工程数量")


def locate_boq_text(tender_text: str, *, cap: int = _BOQ_TEXT_CAP) -> str:
    """定位「工程量清单」正文。排除计量规则(另册);章节段缺真实工程量时,补入分项工程列项区域。"""
    if not (tender_text or "").strip():
        return ""
    seg = ""
    chapter_hits = list(_BOQ_CHAPTER_RE.finditer(tender_text))
    if chapter_hits:
        start = chapter_hits[-1].start()  # 目录在前、正文在后 → 取最后一处(非计量规则)
        nxt = re.search(r"第[一二三四五六七八九十百\d]+章\s", tender_text[start + 10:])
        end = start + 10 + (nxt.start() if nxt else cap)
        seg = tender_text[start:end][:cap]
    # 章节段缺真实工程量信号(清单为另册/仅说明)→ 补入分项工程列项区域供 LLM 据列项估占比。
    if len(_BOQ_SIGNAL.findall(seg)) < 5:
        for kw in _BOQ_LIST_KW:
            i = tender_text.find(kw)
            if i != -1:
                extra = tender_text[i : i + 8000]
                if extra and extra not in seg:
                    seg = (seg + "\n\n【补充·分项工程列项】\n" + extra)[:cap]
                break
    if seg.strip():
        return seg
    for kw in ("分部分项工程量清单", "工程量清单", "工程数量表", "清单项目"):
        i = tender_text.rfind(kw)
        if i != -1:
            return tender_text[i : i + cap]
    return ""


def _to_boq(data: dict[str, Any]) -> TenderBOQ:
    def _f(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    cats: list[BOQCategory] = []
    for row in data.get("categories") or []:
        if isinstance(row, dict) and (row.get("name") or row.get("key_quantities")):
            cats.append(
                BOQCategory(
                    name=str(row.get("name", "") or ""),
                    share_pct=_f(row.get("share_pct")),
                    key_quantities=str(row.get("key_quantities", "") or ""),
                    basis=str(row.get("basis", "") or ""),
                )
            )
    dominant = [c.name for c in cats if c.share_pct >= _DOMINANT_SHARE and c.name]
    if not dominant and cats:
        top = max(cats, key=lambda c: c.share_pct)
        if top.name:
            dominant = [top.name]
    return TenderBOQ(
        total_amount_wan=_f(data.get("total_amount_wan")),
        categories=cats,
        dominant=dominant,
        note=str(data.get("note", "") or ""),
    )


def build_boq(tender_text: str, *, complete: Completion | None = None) -> TenderBOQ:
    """抽招标工程量清单 → 分部分项占比结构。抽不到/失败返回空(不阻断生成)。"""
    text = locate_boq_text(tender_text)
    if not text.strip():
        return TenderBOQ()
    try:
        raw = (complete or _default_complete)(build_boq_prompt(text))
        return _to_boq(_parse_json(raw))
    except Exception:
        logger.warning("工程量清单抽取失败,返回空(不阻断生成)", exc_info=True)
        return TenderBOQ()


# ── 接线助手:把 BOQ 占比/工程量喂给技术卷写作 ───────────────────────────────

# 分部分项分组:把"BOQ 类别名"和"施工方案节标题"各自归到大组,同组才算匹配。
# 用分组(而非裸关键词包含)是为了解决简称差异——如类别"交通安全设施"与节"附属交安…"。
_BOQ_GROUPS = (
    ("路基", ("路基", "土石方", "土方", "地基", "填方", "挖方")),
    ("路面", ("路面", "面层", "基层", "沥青", "水稳")),
    ("排水", ("排水", "管网", "管道", "雨水", "污水", "检查井")),
    ("桥涵", ("桥", "涵", "结构", "挡墙", "构筑")),
    ("交安", ("交安", "交通安全", "标志", "标线", "护栏", "附属", "安全设施")),
    ("绿化", ("绿化", "景观", "苗木", "种植")),
)


def _groups_of(text: str) -> set[str]:
    text = text or ""
    return {g for g, kws in _BOQ_GROUPS if any(k in text for k in kws)}


def match_categories(boq: TenderBOQ, section_title: str) -> list[BOQCategory]:
    """返回与本节相关的 BOQ 类别(类别名与节标题归到同一分部分项大组才算匹配)。"""
    sec_groups = _groups_of(section_title)
    if not sec_groups:
        return []
    return [c for c in boq.categories if _groups_of(c.name) & sec_groups]


def boq_overview(boq: TenderBOQ) -> str:
    """全工程造价结构总览(喂给每个技术节,让写作把笔墨往主导项砸)。"""
    if boq.is_empty():
        return ""
    ranked = sorted(boq.categories, key=lambda c: -c.share_pct)
    parts = "；".join(f"{c.name} 约{c.share_pct:g}%" for c in ranked[:8] if c.name)
    dom = "、".join(boq.dominant) if boq.dominant else (ranked[0].name if ranked else "")
    line = f"本工程造价结构(据招标工程量清单):{parts}。"
    if dom:
        line += (
            f"主导分部分项=【{dom}】:技术卷应把绝大部分篇幅与最细的工艺、具体工程量放在主导项;"
            "占比很小的分部一句话带过、不堆砌无关工艺。"
        )
    return line


def section_boq_brief(boq: TenderBOQ, section_title: str) -> str:
    """本节对应的清单项与工程量(只给匹配到的类别)。无匹配返回空。"""
    cats = match_categories(boq, section_title)
    if not cats:
        return ""
    lines = [
        f"- {c.name}(占比约{c.share_pct:g}%):{(c.key_quantities or '工程量见招标第五章清单').strip()}"
        for c in cats
    ]
    return "本节对应的工程量清单项(写作须引用以下具体工程量):\n" + "\n".join(lines)


def section_node_brief(boq: TenderBOQ, section_title: str) -> str:
    """喂给单个写作节点的 BOQ 简报 = 全局造价占比总览 + 本节对应清单项。"""
    if boq.is_empty():
        return ""
    overview = boq_overview(boq)
    section = section_boq_brief(boq, section_title)
    return (overview + ("\n" + section if section else "")).strip()


def adjust_min_chars(boq: TenderBOQ, section_title: str, base: int) -> int:
    """按占比定详略:本节对应类别占比高→加厚,极小→压到下限。best-effort,无匹配原样返回。"""
    if boq.is_empty() or not base:
        return base
    cats = match_categories(boq, section_title)
    if not cats:
        return base
    share = sum(c.share_pct for c in cats)
    if share >= 40:
        return int(base * 1.6)
    if share >= 15:
        return int(base * 1.15)
    if share <= 4:
        return min(base, 700)
    return base
