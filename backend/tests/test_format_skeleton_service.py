from __future__ import annotations

from schemas.tender import FormatOutlineNode, TenderRequirements
from services.format_skeleton_service import (
    extract_format_template_blocks,
    has_format_skeleton,
    render_all_volume_skeletons,
    render_volume_node_list,
    render_volume_skeleton,
)


def _project_68_requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="萧县2025年农村公路提质改造联网路工程",
        tenderer_name="萧县交通运输局",
        format_outline_tree={
            "commercial": [
                FormatOutlineNode(
                    title="投标文件（商务文件）",
                    children=[
                        FormatOutlineNode(title="一、投标函"),
                        FormatOutlineNode(title="二、法定代表人身份证明或授权委托书"),
                        FormatOutlineNode(title="三、联合体协议书（如有）"),
                        FormatOutlineNode(
                            title="四、投标保证金",
                            children=[
                                FormatOutlineNode(title="（一）投标保函示范文本"),
                                FormatOutlineNode(title="（二）免缴投标保证金承诺函"),
                            ],
                        ),
                        FormatOutlineNode(
                            title="五、项目管理机构",
                            children=[
                                FormatOutlineNode(title="（一）项目管理机构组织机构图"),
                                FormatOutlineNode(title="（二）项目管理机构人员组成表"),
                            ],
                        ),
                        FormatOutlineNode(title="六、拟分包项目情况表"),
                        FormatOutlineNode(
                            title="七、资格审查资料",
                            children=[
                                FormatOutlineNode(title="（一）投标人基本情况表"),
                                FormatOutlineNode(title="（二）近年财务状况"),
                                FormatOutlineNode(title="（三）近年完成的类似项目情况表"),
                                FormatOutlineNode(title="（四）项目经理和项目总工资历表"),
                                FormatOutlineNode(title="（五）投标人信誉情况"),
                                FormatOutlineNode(title="（六）拟委任的其他管理和技术人员汇总表"),
                                FormatOutlineNode(title="（七）项目经理承诺"),
                            ],
                        ),
                        FormatOutlineNode(title="八、商务文件详细评审资料（如有）"),
                        FormatOutlineNode(title="九、诚信投标承诺书"),
                        FormatOutlineNode(title="十、其他材料"),
                    ],
                )
            ],
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件)",
                    children=[
                        FormatOutlineNode(title="一、施工组织设计"),
                        FormatOutlineNode(title="二、其他内容"),
                    ],
                )
            ],
            "pricing": [
                FormatOutlineNode(
                    title="投标文件（报价文件）",
                    children=[
                        FormatOutlineNode(title="一、投标函"),
                        FormatOutlineNode(
                            title="二、工程量清单报价书",
                            children=[
                                FormatOutlineNode(title="（一）投标报价说明"),
                                FormatOutlineNode(title="（二）建设项目投标报价汇总表"),
                                FormatOutlineNode(title="（三）工程量清单汇总表"),
                                FormatOutlineNode(title="（四）分部分项工程量清单计价表"),
                                FormatOutlineNode(title="（五）措施项目清单计价表"),
                                FormatOutlineNode(title="（六）其他项目清单计价表"),
                                FormatOutlineNode(title="（七）规费和税金项目清单计价表"),
                                FormatOutlineNode(title="（八）单位工程投标报价汇总表"),
                                FormatOutlineNode(title="（九）单价分析表"),
                                FormatOutlineNode(title="（十）材料价格表"),
                                FormatOutlineNode(title="（十一）机械台班价格表"),
                                FormatOutlineNode(title="（十二）人工单价表"),
                                FormatOutlineNode(title="（十三）主要材料用量表"),
                                FormatOutlineNode(title="（十四）主要设备用量表"),
                                FormatOutlineNode(title="（十五）暂列金额明细表"),
                                FormatOutlineNode(title="（十六）专业工程暂估价表"),
                                FormatOutlineNode(title="（十七）计日工表"),
                                FormatOutlineNode(title="（十八）总承包服务费计价表"),
                                FormatOutlineNode(title="（十九）招标人供应材料设备一览表"),
                                FormatOutlineNode(title="（二十）承包人提供主要材料和工程设备一览表"),
                                FormatOutlineNode(title="（二十一）投标报价需要说明的其他资料"),
                            ],
                        ),
                    ],
                )
            ],
        },
    )


def test_render_volume_skeleton_preserves_project_68_format_tree() -> None:
    requirements = _project_68_requirements()
    skeletons = render_all_volume_skeletons(
        requirements,
        company_name="安徽正奇建设有限公司",
    )

    commercial = skeletons["commercial"]
    technical = skeletons["technical"]
    pricing = skeletons["pricing"]

    assert "# 萧县2025年农村公路提质改造联网路工程 商务文件" in commercial
    assert "## 一、投标函" in commercial
    assert "## 五、项目管理机构" in commercial
    assert "### （二）项目管理机构人员组成表" in commercial
    assert "## 十、其他材料" in commercial
    assert "## 投标文件（商务文件）" not in commercial

    assert "## 一、施工组织设计" in technical
    assert "## 二、其他内容" in technical

    assert "## 一、投标函" in pricing
    assert "## 二、工程量清单报价书" in pricing
    assert "### （八）单位工程投标报价汇总表" in pricing
    assert "### （二十一）投标报价需要说明的其他资料" in pricing
    assert "## 投标文件（报价文件）" not in pricing


def test_render_volume_node_list_skips_only_root_container() -> None:
    requirements = _project_68_requirements()

    node_list = render_volume_node_list(requirements, "commercial")

    assert "- 四、投标保证金" in node_list
    assert "  - （一）投标保函示范文本" in node_list
    assert "- 投标文件（商务文件）" not in node_list


def test_empty_format_tree_returns_explicit_empty_skeleton() -> None:
    requirements = TenderRequirements(project_name="测试项目")

    assert has_format_skeleton(requirements) is False
    skeleton = render_volume_skeleton(requirements, volume="technical")

    assert skeleton.startswith("# 测试项目 技术文件")
    assert "未提取到技术文件格式目录。" in skeleton


def test_extract_format_template_blocks_embeds_original_forms() -> None:
    requirements = TenderRequirements(
        project_name="测试工程",
        tenderer_name="测试招标人",
        format_outline_tree={
            "commercial": [
                FormatOutlineNode(
                    title="投标文件（商务文件）",
                    children=[
                        FormatOutlineNode(title="一、投标函"),
                        FormatOutlineNode(title="二、项目管理机构人员组成表"),
                    ],
                )
            ],
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件）",
                    children=[FormatOutlineNode(title="一、施工组织设计")],
                )
            ],
            "pricing": [
                FormatOutlineNode(
                    title="投标文件（报价文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
        },
    )
    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    一、投标函
    致：（招标人）
    1.我方已仔细研究招标文件的全部内容，愿以报价文件投标函中的投标总报价实施本工程。
    法定代表人：________
    二、项目管理机构人员组成表
    职务 姓名 职称 证书名称 级别 证号 专业 养老保险 备注
    项目经理 ________ ________ ________ ________ ________ ________ ________ ________
    投标文件（技术文件）
    一、施工组织设计
    按招标文件要求编制施工组织设计。
    投标文件（报价文件）
    一、投标函
    我方愿以人民币（大写）________（¥________）的投标总报价参与本项目投标。
    """

    blocks = extract_format_template_blocks(requirements, tender_text)
    skeleton = render_volume_skeleton(
        requirements,
        volume="commercial",
        company_name="安徽正奇建设有限公司",
        tender_text=tender_text,
    )

    assert any("我方已仔细研究招标文件" in value for value in blocks.values())
    assert "职务 姓名 职称 证书名称 级别 证号 专业 养老保险 备注" in skeleton
    assert "| 项目 | 内容 | 备注 |" not in skeleton


def test_duplicate_bid_letters_are_extracted_by_volume_order() -> None:
    requirements = TenderRequirements(
        project_name="双信封项目",
        format_outline_tree={
            "commercial": [
                FormatOutlineNode(
                    title="投标文件（商务文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件）",
                    children=[FormatOutlineNode(title="一、施工组织设计")],
                )
            ],
            "pricing": [
                FormatOutlineNode(
                    title="投标文件（报价文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
        },
    )
    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    一、投标函
    商务文件投标函：承诺响应投标有效期和工期质量要求。
    投标文件（技术文件）
    一、施工组织设计
    技术文件正文格式要求。
    投标文件（报价文件）
    一、投标函
    报价文件投标函：投标总报价为人民币________元。
    """

    commercial = render_volume_skeleton(
        requirements,
        volume="commercial",
        tender_text=tender_text,
    )
    pricing = render_volume_skeleton(
        requirements,
        volume="pricing",
        tender_text=tender_text,
    )

    assert "商务文件投标函" in commercial
    assert "报价文件投标函" not in commercial
    assert "报价文件投标函" in pricing
    assert "商务文件投标函" not in pricing


def test_generic_other_nodes_do_not_steal_unrelated_templates() -> None:
    requirements = TenderRequirements(
        project_name="泛标题项目",
        format_outline_tree={
            "commercial": [
                FormatOutlineNode(
                    title="投标文件（商务文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件）",
                    children=[
                        FormatOutlineNode(title="一、施工组织设计"),
                        FormatOutlineNode(title="二、其他内容"),
                    ],
                )
            ],
            "pricing": [
                FormatOutlineNode(
                    title="投标文件（报价文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
        },
    )
    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    一、投标函
    商务投标函正文。
    投标文件（技术文件）
    一、施工组织设计
    施工组织正文。
    其他项目清单计价表
    该行属于报价表，不属于技术文件其他内容。
    投标文件（报价文件）
    一、投标函
    报价投标函正文。
    """

    technical = render_volume_skeleton(
        requirements,
        volume="technical",
        tender_text=tender_text,
    )
    pricing = render_volume_skeleton(
        requirements,
        volume="pricing",
        tender_text=tender_text,
    )

    assert "该行属于报价表" not in technical
    assert "报价投标函正文" in pricing


def test_directory_lines_do_not_steal_form_template() -> None:
    requirements = TenderRequirements(
        project_name="目录过滤项目",
        format_outline_tree={
            "commercial": [
                FormatOutlineNode(
                    title="投标文件（商务文件）",
                    children=[FormatOutlineNode(title="一、投标函")],
                )
            ],
            "technical": [
                FormatOutlineNode(
                    title="投标文件（技术文件）",
                    children=[FormatOutlineNode(title="一、施工组织设计")],
                )
            ],
            "pricing": [
                FormatOutlineNode(
                    title="投标文件（报价文件）",
                    children=[
                        FormatOutlineNode(title="一、投标函"),
                        FormatOutlineNode(title="二、已标价工程量清单"),
                    ],
                )
            ],
        },
    )
    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    一、投标函
    商务投标函正文。
    投标文件（技术文件）
    一、施工组织设计
    技术正文。
    投标文件（报价文件）
    一、投标函
    二、已标价工程量清单
    三、其他资料
    一、投标函
    报价投标函正文。
    二、已标价工程量清单
    清单正文。
    """

    pricing = render_volume_skeleton(
        requirements,
        volume="pricing",
        tender_text=tender_text,
    )

    assert "三、其他资料" not in pricing
    assert "报价投标函正文" in pricing


def test_extract_format_pages_dedupes_local_toc_phantom_nodes() -> None:
    from services.format_skeleton_service import extract_format_pages

    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    目 录
    一、投标函
    二、法定代表人身份证明或授权委托书
    三、联合体协议书（如有）
    一、投标函
    致：（招标人）
    我方已仔细研究（招标项目名称）招标文件。
    投 标 人： （盖单位章）
    二、法定代表人身份证明或授权委托书
    投 标 人：
    附：法定代表人身份证正反面扫描件
    """

    pages = extract_format_pages(tender_text)["commercial"]
    titles = [page.title for page in pages]

    assert titles.count("一、投标函") == 1
    bid_letter = next(page for page in pages if page.title == "一、投标函")
    assert "我方已仔细研究" in bid_letter.raw_template


def test_extract_format_pages_keeps_bank_guarantee_clauses_inside_deposit_page() -> None:
    from services.format_skeleton_service import extract_format_pages

    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    四、投标保证金
    （一）投标保函示范文本
    编号：
    致：受益人（招标人）名称
    一、开立人理解根据招标条件，投标人必须提交一份投标保函（以下简称“本保函”），以担保投标人诚信履行义务。
    二、开立人在投标人发生以下情形时承担保证担保责任：
    （1）投标人在投标有效期内撤销投标文件；
    九、本保函自我方法定代表人或授权代表签字并加盖公章之日起生效。
    开立人： （公章）
    五、项目管理机构
    拟为承包本标段工程设立的组织机构以框图方式表示。
    """

    pages = extract_format_pages(tender_text)["commercial"]
    titles = [page.title for page in pages]

    assert "四、投标保证金" in titles
    assert not any(title.startswith("一、开立人理解") for title in titles)
    deposit = next(page for page in pages if page.title == "四、投标保证金")
    assert "九、本保函" in deposit.raw_template
