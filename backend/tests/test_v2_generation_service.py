from __future__ import annotations

import pytest

from agents.form_filler_agent import fill_page_template
from services import v2_generation_service
from services.format_skeleton_service import FormatPage
from services.v2_audit_service import AuditResult, audit_format_layer
from schemas.tender import FormatOutlineNode, TenderRequirements


def test_form_filler_handles_common_tender_placeholders() -> None:
    result = fill_page_template(
        "致：（招标人）\n"
        "我方已仔细研究（招标项目名称） 标段招标文件。\n"
        "3.质量标准： ；工期： 日历天。\n"
        "投 标 人： （盖单位章）",
        {
            "招标人": "长丰县罗塘乡人民政府",
            "项目名称": "长丰县罗塘乡2025年度美丽宜居村庄建设项目",
            "质量": "符合国家现行工程质量验收标准规范合格标准",
            "工期": "90日历天",
            "company_name": "安徽正奇建设有限公司",
        },
        "投标函",
    )

    assert "致：长丰县罗塘乡人民政府" in result.filled_template
    assert "长丰县罗塘乡2025年度美丽宜居村庄建设项目 标段招标文件" in result.filled_template
    assert "质量标准：符合国家现行工程质量验收标准规范合格标准；工期：90日历天。" in result.filled_template
    assert "90日历天日历天" not in result.filled_template


def test_form_filler_replaces_beneficiary_tenderer_name_as_one_field() -> None:
    result = fill_page_template(
        "编号：\n致：受益人（招标人）名称\n开立人获得通知。",
        {"招标人": "长丰县罗塘乡人民政府"},
        "投标保函",
    )

    assert "致：长丰县罗塘乡人民政府" in result.filled_template
    assert "受益人长丰县罗塘乡人民政府名称" not in result.filled_template


def test_v2_technical_volume_uses_writer_content_without_repeating_format_page(
    monkeypatch,
) -> None:
    requirements = TenderRequirements(
        project_name="长丰县罗塘乡2025年度美丽宜居村庄建设项目",
        format_outline_tree={
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件）",
                    children=[
                        FormatOutlineNode(title="一、施工组织设计"),
                        FormatOutlineNode(title="二、其他内容"),
                    ],
                )
            ]
        },
    )

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {"commercial": [FormatPage("一、施工组织设计", "投标文件（技术文件）\n投标人应按评审因素编制。", "prose_section", "technical")]},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda _pages, _requirements: {
            "commercial": [],
            "technical": [
                FormatPage(
                    "一、施工组织设计",
                    "投标文件（技术文件）\n投标人应按评审因素编制。",
                    "prose_section",
                    "technical",
                )
            ],
            "pricing": [],
        },
    )
    monkeypatch.setattr(
        v2_generation_service,
        "fill_page_template",
        lambda raw, profile, title: v2_generation_service.FillResult(
            title=title,
            raw_template=raw,
            filled_template=raw,
            fields=[],
            missing=[],
        ),
    )
    monkeypatch.setattr(
        v2_generation_service,
        "fill_technical_volume",
        lambda **_kwargs: v2_generation_service.VolumeFillResult(
            volume="technical",
            combined="## 一、施工组织设计\n\n施工组织正文。\n\n## 二、其他内容\n\n其他正文。",
        ),
    )
    monkeypatch.setattr(
        v2_generation_service,
        "full_audit",
        lambda **_kwargs: AuditResult(True, [], [], []),
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式\n一、施工组织设计",
    )

    assert package.technical_markdown.count("## 一、施工组织设计") == 1
    assert "投标文件（技术文件）\n投标人应按评审因素编制" not in package.technical_markdown
    assert "施工组织正文" in package.technical_markdown


def test_v2_format_audit_rejects_flattened_form_tables() -> None:
    report = audit_format_layer(
        pages=[
            (
                "（一）投标人基本情况表",
                "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
            )
        ],
        filled_pages=[
            (
                "（一）投标人基本情况表",
                "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n安徽正奇建设有限公司",
            )
        ],
    )

    assert not report.passed
    assert any("表格格式被拍扁" in issue.problem for issue in report.issues)


def test_v2_format_audit_accepts_markdown_table_layout() -> None:
    report = audit_format_layer(
        pages=[
            (
                "（一）投标人基本情况表",
                "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
            )
        ],
        filled_pages=[
            (
                "（一）投标人基本情况表",
                "| 投标人名称 | 安徽正奇建设有限公司 |\n"
                "| --- | --- |\n"
                "| 注册地址 | ________ |\n"
                "| 联系方式 | ________ |",
            )
        ],
    )

    assert report.passed


def test_v2_format_audit_rejects_reconstructed_table_marker() -> None:
    report = audit_format_layer(
        pages=[
            (
                "（一）投标人基本情况表",
                "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
            )
        ],
        filled_pages=[
            (
                "（一）投标人基本情况表",
                '{{tdg_table:bidder_basic_info company_name="安徽正奇建设有限公司"}}',
            )
        ],
    )

    assert not report.passed
    assert any("不是招标文件原样复制" in issue.problem for issue in report.issues)


def test_v2_does_not_reconstruct_bidder_basic_info_table(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {"commercial": [FormatPage("一、投标人基本情况表", "投标人名称\n注册地址 邮政编码", "table_template", "commercial")]},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda _pages, _requirements: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表",
                    "投标人名称\n注册地址 邮政编码",
                    "table_template",
                    "commercial",
                )
            ],
            "technical": [],
            "pricing": [],
        },
    )
    monkeypatch.setattr(
        v2_generation_service,
        "full_audit",
        lambda **_kwargs: AuditResult(True, [], [], []),
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式\n一、投标人基本情况表",
    )

    assert "{{tdg_table:bidder_basic_info" not in package.commercial_markdown
    assert "投标人名称" in package.commercial_markdown


def test_v2_raises_when_locked_table_cannot_be_copied_exactly(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {"commercial": [FormatPage("一、投标人基本情况表", "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________", "table_template", "commercial")]},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda _pages, _requirements: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表",
                    "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
                    "table_template",
                    "commercial",
                )
            ],
            "technical": [],
            "pricing": [],
        },
    )

    with pytest.raises(ValueError, match="锁定格式未达到招标文件原样要求"):
        v2_generation_service.generate_v2_bid_package(
            requirements,
            {},
            company_name="安徽正奇建设有限公司",
            tender_text="第八章 投标文件格式\n一、投标人基本情况表",
        )


def test_v2_allows_locked_format_audit_fail_when_original_docx_export_available(
    monkeypatch,
) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {"commercial": [FormatPage("一、投标人基本情况表", "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________", "table_template", "commercial")]},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda _pages, _requirements: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表",
                    "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
                    "table_template",
                    "commercial",
                )
            ],
            "technical": [],
            "pricing": [],
        },
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式\n一、投标人基本情况表",
        original_format_docx_available=True,
    )

    assert package.audit_result is not None
    assert not package.audit_result.passed


def test_v2_does_not_turn_bid_letters_into_generic_tables(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {"commercial": [FormatPage("一、投标函", "致：（招标人）\n我方已仔细研究（招标项目名称）招标文件。", "letter_template", "commercial")]},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda _pages, _requirements: {
            "commercial": [
                FormatPage(
                    "一、投标函",
                    "致：（招标人）\n我方已仔细研究（招标项目名称）招标文件。",
                    "letter_template",
                    "commercial",
                )
            ],
            "technical": [],
            "pricing": [],
        },
    )
    monkeypatch.setattr(
        v2_generation_service,
        "full_audit",
        lambda **_kwargs: AuditResult(True, [], [], []),
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式\n一、投标函",
    )

    assert "| 项目 | 内容 | 项目 | 内容 |" not in package.commercial_markdown
    assert "致：" in package.commercial_markdown


def test_v2_does_not_turn_bid_letter_with_bill_text_into_table() -> None:
    rendered = v2_generation_service._render_locked_format_content(
        "一、投标函",
        "致：（招标人）\n我方已仔细研究招标文件和工程量清单。",
        "致：长丰县罗塘乡人民政府\n我方已仔细研究招标文件和工程量清单。",
        {},
    )

    assert not rendered.startswith("| 项目 | 内容")
    assert "工程量清单" in rendered


def test_v2_inserts_pagebreak_before_each_top_level_format_page(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {
            "commercial": [
                FormatPage("一、投标函", "致：（招标人）", "letter_template", "commercial"),
                FormatPage("二、授权委托书", "本人（姓名）系（投标人名称）的法定代表人。", "letter_template", "commercial"),
            ]
        },
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda pages, _requirements: {"commercial": pages, "technical": [], "pricing": []},
    )
    monkeypatch.setattr(
        v2_generation_service,
        "full_audit",
        lambda **_kwargs: AuditResult(True, [], [], []),
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式",
    )

    assert package.commercial_markdown.count("<!-- tdg:pagebreak -->") == 4
    assert "## 目 录" in package.commercial_markdown


def test_v2_format_audit_rejects_missing_required_figures() -> None:
    report = audit_format_layer(
        pages=[("项目管理机构组织机构图", "拟为本标段工程设立的组织机构以框图方式表示。")],
        filled_pages=[("项目管理机构组织机构图", "拟设项目经理、技术负责人及各职能部门。")],
    )

    assert not report.passed
    assert any("图表/图片要求未落实" in issue.problem for issue in report.issues)
