"""分卷回归:资格审查证件附录(及其 ### 子标题)必须留在商务卷,不能被甩进技术卷。

历史 bug:#150 商务卷 0 图——证件插图标记被 split_delivery_markdown 错切进技术卷
(① ### 子标题按关键词改判 ② 附录 H2 标题不命中商务关键词)。本测试守住修复。
"""

from __future__ import annotations

from utils.docx_exporter import split_delivery_markdown


def _markers(text: str) -> int:
    return text.count("knowledge_image")


def test_company_evidence_subsections_stay_commercial() -> None:
    md = (
        "# 投标文件\n\n"
        "## 投标函\n\n投标函正文。\n\n"
        "## 附录：资格证明材料（系统自动插入）\n\n"
        "### 营业执照\n\n{{knowledge_image:document_id=1 caption=\"营业执照\"}}\n\n"
        "### 企业资质证书\n\n{{knowledge_image:document_id=2 caption=\"资质\"}}\n\n"
        "### 企业荣誉与信誉证明\n\n{{knowledge_image:document_id=3 caption=\"荣誉\"}}\n\n"
        "## 施工组织设计\n\n技术正文,不含图。\n"
    )
    vols = split_delivery_markdown(md)
    # 三张证件全在商务卷,技术卷不沾
    assert _markers(vols["commercial"]) == 3
    assert _markers(vols["technical"]) == 0


def test_personnel_and_idcard_appendix_route_commercial() -> None:
    md = (
        "# 投标文件\n\n"
        "## 技术标正文\n\n正文。\n\n"
        "## 附录：法定代表人身份证明材料（系统自动插入）\n\n"
        "{{knowledge_image:document_id=10 caption=\"法人身份证\"}}\n\n"
        "## 附录：项目经理 / 项目技术负责人证件材料（系统自动插入）\n\n"
        "{{knowledge_image:document_id=11 caption=\"建造师证\"}}\n\n"
        "## 附录：类似业绩证明材料（系统自动插入）\n\n"
        "{{knowledge_image:document_id=12 caption=\"中标通知书\"}}\n"
    )
    vols = split_delivery_markdown(md)
    assert _markers(vols["commercial"]) == 3
    assert _markers(vols["technical"]) == 0
