from __future__ import annotations

from agents.pricing_agent import (
    extract_pricing_strategy,
    generate_pricing_strategy_report,
    markdown_preserves_pricing_manual_points,
)
from schemas.tender import RequirementItem, SourceReference, TenderRequirements


def test_extract_pricing_strategy_marks_amounts_rates_and_schedule_manual() -> None:
    requirements = TenderRequirements(
        project_name="商务策略测试项目",
        qualification_list=[
            RequirementItem(
                title="付款条件",
                description="工程按月支付进度款，质保金为3%，结算审计后支付。",
                source=SourceReference(source_text="付款条件：质保金为3%"),
            )
        ],
        technical_score_items=[
            RequirementItem(
                title="工期要求",
                description="计划工期120日历天，节点延误将扣分。",
            )
        ],
        invalid_bid_items=[
            RequirementItem(
                title="投标保证金",
                description="投标保证金金额为20万元，未提交保证金否决投标。",
            ),
            RequirementItem(
                title="报价要求",
                description="不得低于成本报价，最高限价1000万元。",
            ),
        ],
    )

    strategy = extract_pricing_strategy(requirements)

    assert strategy.project_name == "商务策略测试项目"
    assert strategy.project_scale == "人工确认"
    assert strategy.payment_terms
    assert strategy.guarantee_requirements
    assert any(item.name == "工期约束" for item in strategy.extracted_conditions)
    assert any("3%" in item.label for item in strategy.manual_fields)
    assert any("20万元" in item.label for item in strategy.manual_fields)
    assert any("1000万元" in item.label for item in strategy.manual_fields)


def test_pricing_report_keeps_manual_points_and_never_quotes_prices() -> None:
    strategy = extract_pricing_strategy(
        TenderRequirements(
            project_name="不编造价格项目",
            qualification_list=[],
            technical_score_items=[],
            invalid_bid_items=[
                RequirementItem(title="清单报价", description="需提交工程量清单综合单价。")
            ],
        )
    )

    report = generate_pricing_strategy_report(strategy)
    text = "\n".join(
        [
            *report.strategy_suggestions,
            *report.risk_warnings,
            *report.commercial_response_notes,
            *report.manual_confirmation_points,
        ]
    )

    assert report.prohibited_auto_pricing is True
    assert "人工确认点" in text
    assert "报价为" not in text
    assert "综合单价为" not in text


def test_markdown_preserves_pricing_manual_points_uses_fill_in_blanks() -> None:
    # Live convention: pricing lines keep an underline blank for manual fill-in.
    assert markdown_preserves_pricing_manual_points(
        "本次投标总报价为________元（大写：________整）。"
    )
    assert markdown_preserves_pricing_manual_points(
        "我单位承诺按招标文件规定的金额（________元）提交投标保证金。"
    )
    # The sanitizer strips "人工确认点" annotations, so the legacy marker alone
    # no longer counts as a preserved manual confirmation.
    assert not markdown_preserves_pricing_manual_points(
        "人工确认点：【待补充】投标总价、工程量清单综合单价"
    )
    # Pricing lines without blanks (auto-filled numbers) do not count either.
    assert not markdown_preserves_pricing_manual_points("投标总价为1000万元。")
    assert not markdown_preserves_pricing_manual_points("施工组织设计正文。________")
