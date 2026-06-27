"""招标覆盖校验提示词:逐条判断标书正文是否"实质响应"了招标的评分点/废标项。

交卷前的最后一道硬闸用它:让 LLM 站在评标委员会视角,对每条评分点/废标项判断标书是否
真正正面响应/实质规避(而非正文里恰好出现个把关键词)。产出纯 JSON,由 v2_audit_service 装配。

只回 index+covered(不要 reason),让长清单的输出不被 token 截断;覆盖判定只消费 covered 布尔,
告警明细用招标条款原文,不依赖 LLM 的 reason。
"""

from __future__ import annotations

import json
from typing import Any

# 正文喂给 LLM 的字符上限。整卷标书超过它会被截断 → 截断时 evaluate_coverage 用全文 bigram
# 救援"被切掉尾部里其实已响应"的条款,避免误判漏→误拦。设为兼顾模型上下文上限的值。
COVERAGE_PROSE_CAP = 120000

_SYSTEM = (
    "你是投标文件废标风险审查总监 + 评标委员会视角质检员,15 年公路/市政/建筑投标审查经验。"
    "任务:对照招标的'评分点/废标项'清单,逐条判断标书正文是否做到了实质响应。"
    "判定铁律:① 必须是'实质响应'——针对该条要求给出了对应的措施/承诺/数据,而不是正文里"
    "恰好出现了个把相关字眼;② 废标项(kind=废标)从严:看不出标书明确、正面地规避了该否决条款,"
    "一律判 covered=false;③ 不臆测正文里没有的内容。只输出合法 JSON,不要解释或 markdown。"
)

_INSTRUCTION = """下面是标书正文,以及需要逐条核对的招标要求清单。请判断每一条是否被标书"实质响应"。

判定标准:
- kind=评分: 标书是否针对该评分点给出了对应的、可量化的工程措施/方案/验收标准(正面响应)。
- kind=废标: 标书是否明确、实质地规避了该否决/废标条款(如满足工期/质量/安全限值、提供了要求的承诺/资料、未出现被禁止的情形)。看不出确切规避就判 false(从严)。

输出纯 JSON(不要 markdown 围栏、不要任何解释文字),covered 用 JSON 布尔值 true/false:
{
  "verdicts": [
    {"index": 0, "covered": true},
    {"index": 1, "covered": false}
  ]
}
verdicts 必须覆盖下面每一条要求,每条一个对象,index 与清单序号一一对应。

## 招标要求清单(逐条核对)
{items_block}

## 标书正文
---
{prose}
---
只输出 JSON。"""


def _items_block(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, it in enumerate(items):
        kind = str(it.get("kind", "") or "")
        title = str(it.get("title", "") or "").strip()
        desc = str(it.get("description", "") or "").strip()
        body = f"{title}：{desc}" if title and desc else (title or desc)
        lines.append(f"[{i}] (kind={kind}) {body}")
    return "\n".join(lines)


def build_coverage_audit_prompt(
    prose_text: str, items: list[dict[str, Any]], *, prose_cap: int = COVERAGE_PROSE_CAP
) -> list[dict[str, str]]:
    user = _INSTRUCTION.replace("{items_block}", _items_block(items)).replace(
        "{prose}", (prose_text or "")[:prose_cap]
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def _truthy_covered(val: Any) -> bool:
    """covered 从严:只认真布尔 True / 明确肯定串。'false'/0/None 等一律 False。"""
    if val is True:
        return True
    if isinstance(val, str):
        s = val.strip().lower()
        return s in {"true", "yes", "1"} or val.strip() in {"是", "已覆盖", "覆盖"}
    return False


def parse_coverage_verdicts(raw: str, count: int) -> list[bool] | None:
    """把 LLM 返回解析成与清单等长的 covered 布尔列表。

    **解析失败 / 非 dict / 无 verdicts(LLM 没真正作答、或 JSON 被截断)→ 返回 None**,
    由上层降级到 bigram 兜底——切勿把"解析失败"当成"全未覆盖"返回全 False,否则会把每条
    废标项误升 critical、永久卡死出标。covered 从严解析;index 容忍字符串数字。
    """
    from agents.parser_agent import (
        _extract_json_object,
        _remove_trailing_commas,
        _strip_markdown_fence,
    )

    try:
        cleaned = _remove_trailing_commas(_extract_json_object(_strip_markdown_fence(raw)))
        data = json.loads(cleaned)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        return None

    flags = [False] * count
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        raw_idx = v.get("index")
        if isinstance(raw_idx, bool):  # True/False 不是合法序号
            continue
        if isinstance(raw_idx, int):
            idx = raw_idx
        elif isinstance(raw_idx, str) and raw_idx.strip().lstrip("-").isdigit():
            idx = int(raw_idx)
        else:
            continue
        if 0 <= idx < count:
            flags[idx] = _truthy_covered(v.get("covered"))
    return flags
