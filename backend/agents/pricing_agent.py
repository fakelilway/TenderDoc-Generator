from __future__ import annotations

import re

from schemas.review import ReviewReport
from schemas.strategy import (
    PricingCondition,
    PricingManualField,
    PricingStrategy,
    PricingStrategyReport,
)
from schemas.tender import RequirementItem, TenderRequirements


PRICING_SYSTEM_PROMPT = """角色扮演：你是一位“商务标报价策略顾问 + 投标合规风险控制师”。
经验背书：你拥有15年以上建筑、市政、公路工程商务标编制和清单报价协同经验，熟悉付款条件、投标保证金、履约担保、工期压缩、最高限价、评标价和低于成本价风险。

人格化工作方式：
- 你只做报价策略、风险提示和商务响应清单，不替人工报价人员填任何金额、费率、综合单价或工程量清单价格。
- 你会把所有具体金额、费率、保证金、单价、总价、成本测算和偏差率标记为人工确认点。
- 你看到招标文件未提供的信息时必须写“人工确认”，不得编造市场价格、成本、竞争对手报价或中标概率。

你的任务：从结构化招标要求中抽取付款、担保、工期、报价和评标价约束，输出报价策略建议、风险提示、商务响应注意事项和人工确认字段。不得编造具体报价，所有清单金额必须由人工填写。"""


PAYMENT_PATTERNS = ("付款", "支付", "预付款", "进度款", "结算", "审计", "质保金")
GUARANTEE_PATTERNS = ("保证金", "保函", "履约担保", "履约保证", "担保")
SCHEDULE_PATTERNS = ("工期", "计划工期", "交付", "竣工", "日历天", "节点")
QUOTE_PATTERNS = ("报价", "清单", "最高限价", "控制价", "评标价", "价格分", "低于成本", "偏差率")
AMOUNT_OR_RATE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:元|万元|亿元|%|％|天|日历天)|[一二三四五六七八九十百千万亿]+(?:元|万元|亿元|天|日历天))"
)


def extract_pricing_strategy(requirements: TenderRequirements) -> PricingStrategy:
    conditions: list[PricingCondition] = []
    payment_terms: list[PricingCondition] = []
    guarantee_requirements: list[PricingCondition] = []
    manual_fields = _default_manual_fields()

    for item in _all_items(requirements):
        text = _item_text(item)
        if _contains_any(text, PAYMENT_PATTERNS):
            condition = _condition("付款条件", text, risk_level="high", manual_verify=True)
            payment_terms.append(condition)
            conditions.append(condition)
        if _contains_any(text, GUARANTEE_PATTERNS):
            condition = _condition("担保/保证金要求", text, risk_level="high", manual_verify=True)
            guarantee_requirements.append(condition)
            conditions.append(condition)
        if _contains_any(text, SCHEDULE_PATTERNS):
            conditions.append(_condition("工期约束", text, risk_level="medium", manual_verify=True))
        if _contains_any(text, QUOTE_PATTERNS):
            conditions.append(_condition("报价/评标价约束", text, risk_level="high", manual_verify=True))

        for value in AMOUNT_OR_RATE_PATTERN.findall(text):
            manual_fields.append(
                PricingManualField(
                    label=f"人工确认数值：{value.strip()}",
                    reason="招标文件出现具体金额、费率、天数或报价相关数值，系统只提示核对，不自动用于报价。",
                    source_text=text[:240],
                )
            )

    deduped_conditions = _dedupe_conditions(conditions)
    return PricingStrategy(
        project_name=requirements.project_name,
        project_scale="人工确认",
        schedule_risk=_risk_from_conditions(deduped_conditions, "工期"),
        payment_terms=_dedupe_conditions(payment_terms),
        competition_intensity="人工确认",
        quote_risk=_risk_from_conditions(deduped_conditions, "报价"),
        guarantee_requirements=_dedupe_conditions(guarantee_requirements),
        manual_fields=_dedupe_manual_fields(manual_fields),
        extracted_conditions=deduped_conditions,
    )


def generate_pricing_strategy_report(
    strategy: PricingStrategy,
    review_report: ReviewReport | None = None,
) -> PricingStrategyReport:
    suggestions = [
        "按招标付款节点、工期约束和担保占用测算现金流压力，形成报价上下限建议，具体金额由人工报价人员填写。",
        "将投标总价、分部分项综合单价、措施费和不可竞争费用列为强制人工复核项。",
        "对最高限价、评标价和低于成本价条款建立单独核对表，避免因商务偏差导致否决投标。",
    ]
    warnings: list[str] = []
    notes = [
        "商务标正文必须保留报价人工确认点，工程量清单不得由系统自动填数。",
        "付款、保证金、履约担保和工期压缩影响需要由商务负责人结合成本底稿确认。",
    ]

    if strategy.payment_terms:
        warnings.append("付款条件已抽取到约束，需人工测算垫资周期和回款风险。")
    else:
        warnings.append("未抽取到明确付款条件，需人工回查招标文件商务条款。")
    if strategy.guarantee_requirements:
        warnings.append("保证金/担保条款已抽取到约束，需核对金额、形式和递交截止时间。")
    if review_report and review_report.has_failures:
        warnings.append("当前审查报告仍有失败项，报价策略只能作为草案参考。")

    manual_points = [
        f"人工确认点：【待补充】{field.label} - {field.reason}"
        for field in strategy.manual_fields
    ]
    if not manual_points:
        manual_points.append("人工确认点：【待补充】投标总价、综合单价、保证金金额和成本测算底稿。")

    return PricingStrategyReport(
        project_name=strategy.project_name,
        strategy_suggestions=suggestions,
        risk_warnings=warnings,
        commercial_response_notes=notes,
        manual_confirmation_points=manual_points,
        prohibited_auto_pricing=True,
    )


def markdown_preserves_pricing_manual_points(markdown: str) -> bool:
    pricing_lines = [
        line
        for line in markdown.splitlines()
        if any(keyword in line for keyword in ("报价", "投标总价", "单价", "清单", "金额"))
    ]
    if not pricing_lines:
        return False
    return any("人工确认点" in line and "待补充" in line for line in pricing_lines)


def _all_items(requirements: TenderRequirements) -> list[RequirementItem]:
    return [
        *requirements.qualification_list,
        *requirements.technical_score_items,
        *requirements.invalid_bid_items,
    ]


def _item_text(item: RequirementItem) -> str:
    return " ".join(
        part
        for part in (item.title, item.description, item.source.source_text)
        if part
    )


def _condition(
    name: str,
    text: str,
    risk_level: str,
    manual_verify: bool,
) -> PricingCondition:
    return PricingCondition(
        name=name,
        value="人工确认",
        risk_level=risk_level,
        source_text=text[:240],
        manual_verify=manual_verify,
    )


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _risk_from_conditions(conditions: list[PricingCondition], keyword: str) -> str:
    return "high" if any(keyword in item.name and item.risk_level == "high" for item in conditions) else "medium"


def _dedupe_conditions(items: list[PricingCondition]) -> list[PricingCondition]:
    seen: set[tuple[str, str]] = set()
    result: list[PricingCondition] = []
    for item in items:
        key = (item.name, item.source_text)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_manual_fields(items: list[PricingManualField]) -> list[PricingManualField]:
    seen: set[tuple[str, str]] = set()
    result: list[PricingManualField] = []
    for item in items:
        key = (item.label, item.source_text)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _default_manual_fields() -> list[PricingManualField]:
    return [
        PricingManualField(label="投标总价", reason="必须由人工根据成本测算和清单确认。"),
        PricingManualField(label="工程量清单综合单价", reason="不得由系统自动生成或补齐。"),
        PricingManualField(label="投标保证金金额", reason="需核对招标文件金额、形式和递交截止时间。"),
        PricingManualField(label="付款条件影响测算", reason="需商务负责人测算现金流和垫资压力。"),
        PricingManualField(label="成本测算底稿", reason="需人工结合企业成本和项目实际确认。"),
    ]
