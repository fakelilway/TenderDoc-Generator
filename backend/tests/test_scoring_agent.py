from __future__ import annotations

from agents.scoring_agent import predict_score
from schemas.tender import RequirementItem, TenderRequirements


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="评分预测项目",
        qualification_list=[],
        technical_score_items=[
            RequirementItem(
                title="施工组织设计 30分",
                description="施工部署、质量安全、进度计划完整得30分。",
            ),
            RequirementItem(
                title="项目班子 20分",
                description="项目经理、技术负责人及主要人员配置合理得20分。",
            ),
        ],
        invalid_bid_items=[],
    )


def test_complete_markdown_scores_higher_than_missing_sections() -> None:
    complete = """# 技术标
## 施工组织设计
施工部署、质量安全、进度计划完整。
## 项目班子
项目经理、技术负责人及主要人员配置合理。
"""
    missing = """# 技术标
## 施工组织设计
施工部署和质量安全措施。
"""

    complete_prediction = predict_score(_requirements(), complete)
    missing_prediction = predict_score(_requirements(), missing)

    assert complete_prediction.predicted_total_score > missing_prediction.predicted_total_score
    assert complete_prediction.win_probability is not None
    assert complete_prediction.win_probability_rationale
    assert complete_prediction.uncertainty_notes
    assert missing_prediction.weaknesses


def test_missing_score_item_gets_clear_reason_and_location_fallback() -> None:
    prediction = predict_score(_requirements(), "# 技术标\n\n只有封面。")

    failed_items = [
        item for item in prediction.items if item.coverage_status == "fail"
    ]
    assert failed_items
    assert "未找到" in failed_items[0].rationale
    assert failed_items[0].location.line_number == 1
