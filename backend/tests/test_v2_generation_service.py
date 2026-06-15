from __future__ import annotations

import pytest

from agents.form_filler_agent import fill_page_template
from services import v2_generation_service
from services.format_skeleton_service import FormatPage
from services.v2_audit_service import AuditResult, audit_format_layer
from schemas.tender import FormatOutlineNode, TenderRequirements


def test_form_filler_handles_common_tender_placeholders() -> None:
    result = fill_page_template(
        "致：（招标人）\n" "我方已仔细研究（招标项目名称） 标段招标文件。\n" "3.质量标准： ；工期： 日历天。\n" "投 标 人： （盖单位章）",
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
        lambda _text: {
            "commercial": [
                FormatPage(
                    "一、施工组织设计", "投标文件（技术文件）\n投标人应按评审因素编制。", "prose_section", "technical"
                )
            ]
        },
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

    # Thin tender technical outline now expands to the canonical deep
    # construction-plan outline (25 sections derived from real winning bids).
    assert "## 第一章 总体施工组织布置及规划" in package.technical_markdown
    assert "## 质量管理体系与质量保证措施" in package.technical_markdown
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
        lambda _text: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表", "投标人名称\n注册地址 邮政编码", "table_template", "commercial"
                )
            ]
        },
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


def test_v2_blocks_when_locked_table_cannot_be_copied_exactly(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表",
                    "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
                    "table_template",
                    "commercial",
                )
            ]
        },
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
    )

    # 审查发现严重问题时不再抛错（见 901544f）：阻断下游审查/导出流水线，
    # 但仍返回已生成内容供人工预览。
    assert package.audit_blocked is True
    assert package.audit_result is not None
    assert package.audit_result.passed is False
    assert any(issue.severity == "critical" for issue in package.audit_result.all_issues)


def test_v2_skips_reconstructed_format_audit_when_original_export_available(
    monkeypatch,
) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {
            "commercial": [
                FormatPage(
                    "一、投标人基本情况表",
                    "投标人名称\n注册地址 邮政编码\n联系方式 联系人 电话\n________",
                    "table_template",
                    "commercial",
                )
            ]
        },
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
    monkeypatch.setattr(
        v2_generation_service,
        "fill_technical_volume",
        lambda **_kwargs: v2_generation_service.VolumeFillResult(
            volume="technical",
            combined=(
                "测试项目施工组织设计正文。\n"
                "施工部署严格响应招标文件。\n"
                "质量、安全、进度、环保措施完整。\n"
                "机械人员投入结合项目特点安排。\n"
                "竣工资料和缺陷修复按合同执行。"
            ),
        ),
    )

    package = v2_generation_service.generate_v2_bid_package(
        requirements,
        {},
        company_name="安徽正奇建设有限公司",
        tender_text="第八章 投标文件格式\n一、投标人基本情况表",
        original_format_docx_available=True,
    )

    assert package.audit_result is not None
    assert package.audit_result.format_issues == []
    # 原格式导出可用时跳过重建格式审查；商务卷以标题开头，
    # 其余为 _enrich_commercial_markdown 追加的合规正文（见 cb373ac）。
    assert package.commercial_markdown.startswith("# 测试项目 商务文件")


def test_v2_original_format_fails_when_content_writer_fails(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    def fail_writer(**_kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(v2_generation_service, "fill_technical_volume", fail_writer)

    with pytest.raises(ValueError, match="施工方案正文生成失败"):
        v2_generation_service.generate_v2_bid_package(
            requirements,
            {},
            company_name="安徽正奇建设有限公司",
            tender_text="第八章 投标文件格式",
            original_format_docx_available=True,
        )


def test_v2_raises_when_pdf_original_format_copy_fails(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    def fail_copy(*_args, **_kwargs):
        raise RuntimeError("boom")

    # Both the image+fields primary and the plain page-image fallback fail → hard error.
    monkeypatch.setattr(
        "services.original_docx_format_service.build_original_format_docx_from_pdf_with_fields",
        fail_copy,
    )
    monkeypatch.setattr(
        "services.original_docx_format_service.build_original_format_docx_from_pdf",
        fail_copy,
    )

    with pytest.raises(ValueError, match="PDF 招标文件原格式复制失败"):
        v2_generation_service.generate_v2_bid_package(
            requirements,
            {},
            company_name="安徽正奇建设有限公司",
            tender_text="第八章 投标文件格式",
            original_format_docx_available=True,
            tender_bytes=b"not a pdf",
        )


def test_v2_does_not_turn_bid_letters_into_generic_tables(monkeypatch) -> None:
    requirements = TenderRequirements(project_name="测试项目")

    monkeypatch.setattr(
        v2_generation_service,
        "extract_format_pages",
        lambda _text: {
            "commercial": [
                FormatPage(
                    "一、投标函",
                    "致：（招标人）\n我方已仔细研究（招标项目名称）招标文件。",
                    "letter_template",
                    "commercial",
                )
            ]
        },
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
                FormatPage(
                    "二、授权委托书", "本人（姓名）系（投标人名称）的法定代表人。", "letter_template", "commercial"
                ),
            ]
        },
    )
    monkeypatch.setattr(
        v2_generation_service,
        "assign_page_volumes",
        lambda pages, _requirements: {
            "commercial": pages,
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


def test_kb_qualification_tables_filters_noise_and_builds_tables(monkeypatch) -> None:
    """C1:业绩/人员汇总表——构表正确、脏人名被过滤掉。"""
    monkeypatch.setattr(
        "services.knowledge_service.list_performance_records",
        lambda limit=15: [
            {"name": "某二级公路改建工程", "amount": "1500万元", "year": "2024", "type": "公路工程"},
        ],
    )
    monkeypatch.setattr(
        "services.knowledge_service.list_key_personnel",
        lambda limit=40: [
            {"name": "江舟", "certs": "一级建造师证"},
            {"name": "微信图片", "certs": "职称证书"},  # 噪声,应被过滤
            {"name": "施工员吴", "certs": "职称证书"},  # 噪声,应被过滤
        ],
    )

    md = v2_generation_service._kb_qualification_tables_markdown()

    assert "| 项目名称 | 中标金额 | 年份 | 类型 |" in md
    assert "某二级公路改建工程" in md and "1500万元" in md
    assert "| 姓名 | 持有证书 |" in md
    assert "江舟" in md
    assert "微信图片" not in md  # 噪声人名被过滤
    assert "施工员吴" not in md


def test_kb_qualification_tables_empty_when_no_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.knowledge_service.list_performance_records", lambda limit=15: []
    )
    monkeypatch.setattr(
        "services.knowledge_service.list_key_personnel", lambda limit=40: []
    )
    assert v2_generation_service._kb_qualification_tables_markdown() == ""


# 用 CompanyProfile 真实字段名核对 profile 匹配:旧代码取 schema 里不存在的键名
# (project_manager/pm_certificate/qualification_level/safety_license/business_license),
# 这些字段恒空。下面两条测试在旧键名下会失败,修复后通过。
_PROFILE_FIELDS = {
    "company_name": "安徽正奇建设有限公司",
    "qualification_grade": "建筑工程施工总承包一级",
    "safety_license_no": "(皖)JZ安许证字[2021]007",
    "credit_code": "91340000MA2ABCDE3K",
    "project_manager_name": "李明",
    "project_manager_cert": "皖一级建造师A123456",
}


def test_match_profile_field_uses_real_schema_keys() -> None:
    assert (
        v2_generation_service._match_profile_field("资质要求响应", _PROFILE_FIELDS)
        == "建筑工程施工总承包一级"
    )
    assert (
        v2_generation_service._match_profile_field("安全生产许可证", _PROFILE_FIELDS)
        == "(皖)JZ安许证字[2021]007"
    )
    assert (
        v2_generation_service._match_profile_field("营业执照", _PROFILE_FIELDS)
        == "91340000MA2ABCDE3K"
    )


def test_enrich_commercial_fills_project_manager_from_profile() -> None:
    requirements = TenderRequirements(project_name="测试项目")
    # header-only 触发 enrich 路径
    enriched = v2_generation_service._enrich_commercial_markdown(
        "## 商务文件\n", requirements, _PROFILE_FIELDS
    )
    assert "李明" in enriched  # project_manager_name 被正确取出
    assert "皖一级建造师A123456" in enriched  # project_manager_cert
