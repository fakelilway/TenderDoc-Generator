from pathlib import Path

from services import bid_gap_eval

REFERENCE_TEMPLATE = (
    Path(__file__).parent / "fixtures" / "bid_templates" / "road_first_envelope_template.json"
)

# An AI draft that only covers the施工组织设计 technical chapters and omits the
# project management chapter, qualification materials, SME declaration and the
# construction appendices that a real bid contains.
AI_MARKDOWN = """# 萧县2025年农村公路提质改造联网路工程投标文件

## 第一章、总体施工组织布置及规划
本工程总体施工部署与资源配置说明。

## 第二章、主要工程项目的施工方案、方法与技术措施
路基、路面施工方案与技术措施。

## 第三章、工期保证体系及保证措施
进度计划与工期保证措施。

## 第四章、工程质量管理体系及保证措施
质量管理体系与验收标准。

## 投标报价说明
人工确认点：投标总价及工程量清单单价需人工核对后填写。
"""


def test_section_key_strips_numbering_prefix() -> None:
    assert bid_gap_eval.section_key("六、项目管理机构") == "项目管理机构"
    assert bid_gap_eval.section_key("附表一、施工总体计划表") == "施工总体计划表"
    assert bid_gap_eval.section_key("第一章、总体施工组织布置及规划") == "总体施工组织布置及规划"


def test_extract_markdown_structure_counts_headings_and_manual_points() -> None:
    structure = bid_gap_eval.extract_markdown_structure(AI_MARKDOWN)
    assert "第一章、总体施工组织布置及规划" in structure["sections"]
    assert structure["total_chars"] > 0
    assert structure["manual_confirmation_points"], "人工确认点 should be detected"


def test_evaluate_gap_detects_missing_real_bid_sections() -> None:
    template, reference_total_chars = bid_gap_eval.load_reference_template(
        REFERENCE_TEMPLATE
    )
    structure = bid_gap_eval.extract_markdown_structure(AI_MARKDOWN)
    report = bid_gap_eval.evaluate_gap(
        template, structure, reference_total_chars=reference_total_chars, ai_source="bid.md"
    )

    joined_issues = "\n".join(report["issues"])
    # The test method requires detecting these specific real-bid gaps.
    assert "项目管理机构" in joined_issues
    assert "资格审查" in joined_issues
    assert "中小企业声明函" in joined_issues
    assert "施工附表" in joined_issues
    # The reference template has 8 appendices, none of which the AI draft has.
    assert len(report["missing_appendix_sections"]) == 8
    assert report["appendix_coverage"] == 0.0
    assert report["main_section_coverage"] < 1.0


def test_evaluate_gap_reports_length_ratio_when_reference_known() -> None:
    template, _ = bid_gap_eval.load_reference_template(REFERENCE_TEMPLATE)
    structure = bid_gap_eval.extract_markdown_structure(AI_MARKDOWN)
    report = bid_gap_eval.evaluate_gap(
        template, structure, reference_total_chars=100000, ai_source="bid.md"
    )
    assert report["length_ratio"] is not None
    assert 0.0 <= report["length_ratio"] < 0.5
    assert any("篇幅" in issue for issue in report["issues"])


def test_render_markdown_report_lists_issues() -> None:
    template, _ = bid_gap_eval.load_reference_template(REFERENCE_TEMPLATE)
    structure = bid_gap_eval.extract_markdown_structure(AI_MARKDOWN)
    report = bid_gap_eval.evaluate_gap(template, structure, ai_source="bid.md")
    markdown = bid_gap_eval.render_markdown_report(report)
    assert "真实投标文件差距评估报告" in markdown
    assert "差距问题清单" in markdown
    assert "项目管理机构" in markdown


def test_load_reference_template_rejects_unknown_suffix(tmp_path: Path) -> None:
    bogus = tmp_path / "ref.csv"
    bogus.write_text("x", encoding="utf-8")
    try:
        bid_gap_eval.load_reference_template(bogus)
    except ValueError:
        return
    raise AssertionError("expected ValueError for unsupported reference type")


def test_load_ai_structure_supports_markdown(tmp_path: Path) -> None:
    md = tmp_path / "bid.md"
    md.write_text(AI_MARKDOWN, encoding="utf-8")
    structure = bid_gap_eval.load_ai_structure(md)
    assert structure["sections"]
