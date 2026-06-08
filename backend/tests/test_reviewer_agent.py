from agents.reviewer_agent import (
    REVIEWER_SYSTEM_PROMPT,
    find_markdown_location,
    load_invalid_bid_rules,
    review,
)
from schemas.tender import RequirementItem, TenderRequirements


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="测试项目",
        qualification_list=[
            RequirementItem(title="项目经理", description="项目经理须具备一级建造师"),
            RequirementItem(title="安全生产许可证", description="具备安全生产许可证"),
        ],
        technical_score_items=[RequirementItem(title="工期", description="进度计划响应工期要求")],
        invalid_bid_items=[RequirementItem(title="保证金", description="未提交投标保证金按无效投标处理")],
    )


def test_load_invalid_bid_rules_contains_common_items() -> None:
    rules = load_invalid_bid_rules()
    rule_ids = {rule.id for rule in rules}

    assert "project_manager_certificate" in rule_ids
    assert "safety_production_license" in rule_ids


def test_reviewer_prompt_defines_role_experience_and_task() -> None:
    assert "角色扮演" in REVIEWER_SYSTEM_PROMPT
    assert "经验背书" in REVIEWER_SYSTEM_PROMPT
    assert "你的任务" in REVIEWER_SYSTEM_PROMPT


def test_review_marks_missing_required_content_as_fail() -> None:
    report = review(
        _requirements(),
        "## 施工组织设计\n\n本方案说明进度计划和质量保证措施。",
    )
    failed_rules = {
        finding.rule for finding in report.findings if finding.status == "fail"
    }

    assert report.has_failures
    assert "project_manager_certificate" in failed_rules
    assert "safety_production_license" in failed_rules
    assert all(
        finding.location.paragraph_index is not None for finding in report.findings
    )


def test_review_passes_when_markdown_covers_requirements() -> None:
    markdown = """## 资格响应

项目经理具备一级建造师注册证书。
投标人具备有效安全生产许可证。
已按要求提交投标保证金。
施工组织设计包含进度计划和工期保证措施。
"""

    report = review(_requirements(), markdown)

    assert "project_manager_certificate" in {
        finding.rule for finding in report.findings if finding.status == "pass"
    }
    assert report.fail_count == 0


def test_find_markdown_location_returns_line_and_snippet() -> None:
    location = find_markdown_location(
        "# 标书\n\n项目经理具备一级建造师注册证书。",
        ["一级建造师"],
    )

    assert location.line_number == 3
    assert "一级建造师" in location.snippet


def test_review_warns_when_pricing_manual_confirmation_is_missing() -> None:
    requirements = TenderRequirements(
        project_name="报价审查项目",
        qualification_list=[],
        technical_score_items=[],
        invalid_bid_items=[
            RequirementItem(title="清单报价", description="需提交工程量清单综合单价。")
        ],
    )

    missing_report = review(requirements, "## 商务标\n\n工程量清单综合单价完整。")
    preserved_report = review(
        requirements,
        "## 商务标\n\n人工确认点：【待补充】工程量清单综合单价。",
    )

    assert "pricing_manual_confirmation" in {
        finding.rule for finding in missing_report.findings if finding.status == "warning"
    }
    assert "pricing_manual_confirmation" in {
        finding.rule for finding in preserved_report.findings if finding.status == "pass"
    }
