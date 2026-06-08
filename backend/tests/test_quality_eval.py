from pathlib import Path

from services import quality_eval

MANIFEST = Path(__file__).parent / "fixtures" / "quality_eval" / "manifest.json"


def test_parse_accuracy_identical_is_perfect() -> None:
    parsed = {
        "project_name": "某工程",
        "qualification_list": [{"title": "建筑总承包二级"}],
        "technical_score_items": [{"title": "施工组织设计"}],
        "invalid_bid_items": [{"title": "未提交保证金"}],
    }
    assert quality_eval.parse_accuracy(parsed, parsed) == 1.0


def test_parse_accuracy_partial_is_between_zero_and_one() -> None:
    expected = {
        "project_name": "某工程",
        "qualification_list": [{"title": "建筑总承包二级"}, {"title": "安全许可证"}],
        "technical_score_items": [{"title": "施工组织设计"}, {"title": "进度计划"}],
        "invalid_bid_items": [{"title": "未提交保证金"}, {"title": "未盖章"}],
    }
    parsed = {
        "project_name": "某工程",
        "qualification_list": [{"title": "建筑总承包二级"}],
        "technical_score_items": [{"title": "施工组织设计"}],
        "invalid_bid_items": [{"title": "未提交保证金"}],
    }
    score = quality_eval.parse_accuracy(parsed, expected)
    assert 0.0 < score < 1.0


def test_section_completeness() -> None:
    markdown = "# 标书\n## 施工组织设计\n内容\n## 项目管理机构\n内容\n"
    sections = ["施工组织设计", "项目管理机构", "进度计划", "安全文明施工"]
    assert quality_eval.section_completeness(markdown, sections) == 0.5
    assert quality_eval.section_completeness(markdown, []) == 1.0


def test_invalid_detection_rate() -> None:
    markdown = "已提交投标保证金，投标文件已盖章。"
    items = [
        {"title": "未提交投标保证金", "keyword": "投标保证金"},
        {"title": "投标文件未盖章", "keyword": "盖章"},
        {"title": "未提供授权书", "keyword": "授权书"},
    ]
    # 投标保证金 and 盖章 are addressed; 授权书 is not.
    assert quality_eval.invalid_detection_rate(markdown, items) == round(2 / 3, 4)
    assert quality_eval.invalid_detection_rate(markdown, []) == 1.0
    # Plain string items are matched directly.
    assert quality_eval.invalid_detection_rate("已盖章", ["盖章"]) == 1.0


def test_manual_edit_ratio_identical_is_zero() -> None:
    text = "# 标书\n## 施工组织设计\n内容完整。\n"
    assert quality_eval.manual_edit_ratio(text, text) == 0.0
    assert quality_eval.manual_edit_ratio(text, "") == 0.0
    assert quality_eval.manual_edit_ratio(text, "完全不同的文本内容") > 0.0


def test_evaluate_case_returns_all_metrics() -> None:
    case = {
        "name": "样本",
        "expected_parsed": {"project_name": "某工程"},
        "parsed": {"project_name": "某工程"},
        "reference_sections": ["施工组织设计"],
        "generated_markdown": "## 施工组织设计\n内容",
        "expected_invalid_items": ["未提交保证金"],
        "reference_markdown": "## 施工组织设计\n内容",
        "elapsed_seconds": 12.5,
    }
    result = quality_eval.evaluate_case(case)
    metrics = result["metrics"]
    assert set(metrics) == {
        "parse_accuracy",
        "section_completeness",
        "invalid_detection_rate",
        "manual_edit_ratio",
        "elapsed_seconds",
    }
    assert metrics["elapsed_seconds"] == 12.5


def test_eval_set_has_at_least_five_cases() -> None:
    eval_set = quality_eval.load_eval_set(MANIFEST)
    assert len(eval_set) >= 5


def test_run_eval_over_fixture_set_aggregates_metrics() -> None:
    eval_set = quality_eval.load_eval_set(MANIFEST)
    report = quality_eval.run_eval(eval_set, version="v-test", generated_at="2026-06-08")

    assert report["case_count"] >= 5
    aggregate = report["aggregate"]
    for key in (
        "parse_accuracy",
        "section_completeness",
        "invalid_detection_rate",
        "manual_edit_ratio",
        "total_elapsed_seconds",
        "avg_elapsed_seconds",
    ):
        assert key in aggregate
    # Parser fixtures are intentionally imperfect, so accuracy is below 1.
    assert 0.0 < aggregate["parse_accuracy"] < 1.0
    assert aggregate["total_elapsed_seconds"] > 0.0


def test_render_markdown_report_includes_labels_and_trend() -> None:
    eval_set = quality_eval.load_eval_set(MANIFEST)
    report = quality_eval.run_eval(eval_set, version="v1", generated_at="2026-06-08")
    history = [
        {"version": "v0", "generated_at": "2026-06-01", "aggregate": report["aggregate"]},
        {"version": "v1", "generated_at": "2026-06-08", "aggregate": report["aggregate"]},
    ]
    markdown = quality_eval.render_markdown_report(report, history=history)
    assert "解析准确率" in markdown
    assert "章节完整率" in markdown
    assert "废标检出率" in markdown
    assert "版本趋势" in markdown
    assert "v0" in markdown and "v1" in markdown


def test_history_append_and_load(tmp_path: Path) -> None:
    history_path = tmp_path / "history.jsonl"
    report_a = quality_eval.build_report([], version="v1", generated_at="2026-06-01")
    report_b = quality_eval.build_report([], version="v2", generated_at="2026-06-08")

    quality_eval.append_history(history_path, report_a)
    history = quality_eval.append_history(history_path, report_b)

    assert len(history) == 2
    assert [entry["version"] for entry in history] == ["v1", "v2"]
