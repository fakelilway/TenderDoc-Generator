from __future__ import annotations

from agents.pricing_agent import extract_pricing_strategy
from agents.response_matrix_agent import build_response_matrix
from agents.reviewer_agent import review
from schemas.tender import RequirementItem, TenderRequirements


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="矩阵测试项目",
        qualification_list=[
            RequirementItem(title="企业资质", description="具备建筑工程施工总承包资质。")
        ],
        technical_score_items=[
            RequirementItem(title="施工组织设计 30分", description="施工部署完整。")
        ],
        invalid_bid_items=[
            RequirementItem(title="保证金", description="未提交投标保证金否决投标。"),
            RequirementItem(title="签章", description="投标文件未按要求签章否决投标。"),
        ],
    )


def test_response_matrix_contains_every_invalid_bid_item_and_locations() -> None:
    markdown = """# 商务响应
企业资质：具备建筑工程施工总承包资质。
投标保证金：人工确认点：【待补充】保证金金额和保函形式。

# 技术响应
施工组织设计：施工部署完整。

# 签章承诺
投标文件按要求签章。
"""
    requirements = _requirements()
    matrix = build_response_matrix(
        7,
        requirements,
        markdown,
        review_report=review(requirements, markdown),
        pricing_strategy=extract_pricing_strategy(requirements),
    )

    invalid_rows = [
        row for row in matrix.rows if row.requirement_type == "invalid_bid_item"
    ]
    assert len(invalid_rows) == len(requirements.invalid_bid_items)
    assert all(row.response_location.line_number for row in invalid_rows)
    assert invalid_rows[0].response_section == "商务响应"
    assert matrix.total_invalid_bid_count == 2


def test_response_matrix_includes_commercial_manual_fields() -> None:
    requirements = _requirements()
    strategy = extract_pricing_strategy(requirements)

    matrix = build_response_matrix(
        9,
        requirements,
        "# 商务响应\n人工确认点：【待补充】投标总价、保证金金额。",
        pricing_strategy=strategy,
    )

    commercial_rows = [
        row for row in matrix.rows if row.requirement_type == "commercial_manual_field"
    ]
    assert commercial_rows
    assert all(row.manual_confirmation_required for row in commercial_rows)
    assert any("投标总价" in row.requirement_title for row in commercial_rows)
