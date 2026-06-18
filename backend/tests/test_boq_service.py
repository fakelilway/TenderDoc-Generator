"""工程量清单(BOQ)抽取 + 按占比驱动技术卷详略的纯逻辑测试(注入假LLM,不真调)。"""

from __future__ import annotations

from schemas.tender_spec import BOQCategory, TenderBOQ
from services import boq_service as b


def _boq() -> TenderBOQ:
    return TenderBOQ(
        total_amount_wan=1000.0,
        categories=[
            BOQCategory(name="路基工程", share_pct=90.0, key_quantities="路基填方50万m³"),
            BOQCategory(name="路面工程", share_pct=7.0, key_quantities="水稳基层8万m²"),
            BOQCategory(name="交通安全设施", share_pct=3.0, key_quantities="标线2km"),
        ],
        dominant=["路基工程"],
    )


def test_to_boq_parses_and_marks_dominant() -> None:
    data = {
        "total_amount_wan": 1000,
        "note": "按控制价分部合计",
        "categories": [
            {"name": "路基工程", "share_pct": 90, "key_quantities": "填方50万m³", "basis": "金额"},
            {"name": "路面工程", "share_pct": 7, "key_quantities": "水稳8万m²"},
            {"name": "交安", "share_pct": 3, "key_quantities": "标线"},
        ],
    }
    boq = b._to_boq(data)
    assert len(boq.categories) == 3
    assert boq.total_amount_wan == 1000
    assert boq.dominant == ["路基工程"]  # ≥25% 为主导,只有路基(90)
    assert not boq.is_empty()


def test_to_boq_falls_back_to_top_when_none_dominant() -> None:
    data = {"categories": [
        {"name": "A", "share_pct": 20}, {"name": "B", "share_pct": 18}, {"name": "C", "share_pct": 10},
    ]}
    boq = b._to_boq(data)
    assert boq.dominant == ["A"]  # 无人过25% → 取占比最高


def test_locate_boq_text_picks_real_chapter_over_toc_and_rules() -> None:
    t = (
        "目录\n第五章 工程量清单 …………… 50\n第八章 工程量清单计量规则（另册）\n"
        "正文\n第五章 工程量清单\n分部分项：路基填方50万m³、水稳基层8万m²\n第六章 图纸"
    )
    loc = b.locate_boq_text(t)
    assert "路基填方50万m³" in loc      # 抓到真正文那段
    assert "计量规则" not in loc        # 不抓"计量规则"(另册)
    assert "第六章" not in loc
    assert b.locate_boq_text("") == ""


def test_match_categories_groups_handle_abbrev() -> None:
    boq = _boq()
    assert [c.name for c in b.match_categories(boq, "路基(土石方)及地基处理工程施工方案")] == ["路基工程"]
    assert [c.name for c in b.match_categories(boq, "路面工程施工方案(基层与面层)")] == ["路面工程"]
    # "交通安全设施" 类别 ↔ "附属交安" 节:靠分组匹配上(简称差异)
    assert [c.name for c in b.match_categories(boq, "附属交安与绿化工程施工方案")] == ["交通安全设施"]
    # 进度节无对应分部 → 不匹配
    assert b.match_categories(boq, "施工总进度计划与工期保证措施") == []


def test_boq_overview_and_section_brief() -> None:
    boq = _boq()
    ov = b.boq_overview(boq)
    assert "路基工程 约90%" in ov and "主导分部分项=【路基工程】" in ov
    sec = b.section_boq_brief(boq, "路基(土石方)及地基处理工程施工方案")
    assert "路基填方50万m³" in sec
    assert b.section_boq_brief(boq, "施工总进度计划与工期保证措施") == ""
    # 单节简报 = 总览 + 本节清单项
    node = b.section_node_brief(boq, "路面工程施工方案(基层与面层)")
    assert "造价结构" in node and "水稳基层8万m²" in node


def test_adjust_min_chars_by_share() -> None:
    boq = _boq()
    assert b.adjust_min_chars(boq, "路基(土石方)及地基处理工程施工方案", 2000) == 3200  # 90% → 1.6x
    assert b.adjust_min_chars(boq, "附属交安与绿化工程施工方案", 1500) == 700          # 3% → 压下限
    assert b.adjust_min_chars(boq, "施工总进度计划与工期保证措施", 2200) == 2200        # 无匹配 → 原样
    assert b.adjust_min_chars(TenderBOQ(), "路基工程施工方案", 2000) == 2000            # 空BOQ → 原样


def test_build_boq_with_injected_complete() -> None:
    fake = '{"total_amount_wan":1000,"categories":[{"name":"路基工程","share_pct":90,"key_quantities":"填方50万m³"}]}'
    tender = "第五章 工程量清单\n路基填方50万m³\n第六章 图纸"
    boq = b.build_boq(tender, complete=lambda _m: fake)
    assert boq.dominant == ["路基工程"]
    assert boq.categories[0].key_quantities == "填方50万m³"


def test_build_boq_empty_when_no_chapter() -> None:
    assert b.build_boq("没有清单的招标正文").is_empty()


def test_boq_brief_reaches_writer_prompt() -> None:
    """端到端接线:BOQ 简报喂进技术卷写作 prompt,出现造价占比块与'按占比详略'规则。"""
    from prompts.generator_prompt import build_node_fill_prompt

    brief = b.section_node_brief(_boq(), "路基(土石方)及地基处理工程施工方案")
    msgs = build_node_fill_prompt(
        node_title="路基(土石方)及地基处理工程施工方案",
        project_name="某农村公路工程",
        requirements={},
        company_name="安徽正奇建设有限公司",
        boq_brief=brief,
    )
    user = msgs[-1]["content"]
    assert "本工程量清单(BOQ)与造价占比" in user
    assert "路基填方50万m³" in user
    assert "工程量清单优先" in user  # 写作规则已注入
    # 不传 boq_brief 时不应出现该块
    msgs2 = build_node_fill_prompt(
        node_title="x", project_name="x", requirements={}, company_name="x"
    )
    assert "本工程量清单(BOQ)与造价占比" not in msgs2[-1]["content"]
