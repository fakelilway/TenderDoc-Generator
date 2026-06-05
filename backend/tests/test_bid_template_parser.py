from __future__ import annotations

from utils.bid_template_parser import parse_bid_template_pages


def test_parse_bid_template_pages_extracts_real_bid_structure() -> None:
    pages = [
        "第1页/共892页",
        "第一信封\n萧县2025年农村公路提质改造联网路工程（项目名称）\n投标文件\n（商务及技术文件）\n投标人：安徽正奇建设有限公司（盖单位章）",
        "目录\n一、投标函及投标函附录\n二、授权委托书或法定代表人身份证明",
        "一、投标函及投标函附录\n（一）投标函\n萧县交通运输局：",
        "二、授权委托书或法定代表人身份证明\n（一）授权委托书\n本人许明英（姓名）系安徽正奇建设有限公司\n身份证号码：340111197605197542\n联系人 吴鹏 电话 15056565642",
        "三、联合体协议书\n无",
        "四、投标保证金\n本项目免收中小微企业投标保证金",
        "五、施工组织设计\n投标人应按以下要点编制施工组织设计",
        "施工组织设计\n编制单位：安徽正奇建设有限公司",
        "目录\n第一章、总体施工组织布置及规划...............................................................17\n第二章、主要工程项目的施工方案、方法与技术措施.............................110\n附表一、施工总体计划表.................................................................................785",
    ]
    pages.extend([""] * 800)
    pages[24] = "第一章、总体施工组织布置及规划\n第一节、工程概况描述"
    pages[117] = "第二章、主要工程项目的施工方案、方法与技术措施\n第一节、交通导行方案"
    pages[792] = "附表一、施工总体计划表\n年度 月份 主要工程项目"

    template = parse_bid_template_pages(
        pages,
        source_file="sample.pdf",
        template_name="公路工程第一信封模板样本",
    )

    assert template.project_name == "萧县2025年农村公路提质改造联网路工程"
    assert template.company_name == "安徽正奇建设有限公司"
    assert template.envelope_type == "第一信封"
    assert template.document_type == "投标文件（商务及技术文件）"
    assert template.main_sections[0].title == "一、投标函及投标函附录"
    assert template.main_sections[0].start_page == 4
    assert template.main_sections[0].end_page == 4
    assert "340111197605197542" not in template.main_sections[1].sample_snippet
    assert "15056565642" not in template.main_sections[1].sample_snippet
    assert "【身份证号已脱敏】" in template.main_sections[1].sample_snippet
    assert template.main_sections[4].section_type == "construction_design"
    assert template.construction_design_sections[0].title == "第一章、总体施工组织布置及规划"
    assert template.construction_design_sections[0].start_page == 25
    assert template.construction_design_sections[1].start_page == 118
    assert template.appendix_sections[0].title == "附表一、施工总体计划表"
    assert template.appendix_sections[0].section_type == "appendix"
    assert "年度 月份" in template.appendix_sections[0].sample_snippet
