from types import SimpleNamespace

from prompts.generator_prompt import build_node_fill_prompt
from services.v2_generation_service import _distribute_requirement_items


def _user_content(messages) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def test_prompt_injects_score_and_invalid_items() -> None:
    messages = build_node_fill_prompt(
        node_title="施工组织设计",
        project_name="测试项目",
        requirements={},
        company_name="安徽正奇建设有限公司",
        score_items=[
            {"title": "质量保证措施", "description": "提供完整的质量管理体系和检验计划"},
        ],
        invalid_items=[
            {"title": "未提供安全生产许可证", "description": "缺少有效安全生产许可证将被否决"},
        ],
    )
    content = _user_content(messages)

    assert "本节点须正面响应的评分点" in content
    assert "质量保证措施" in content
    assert "提供完整的质量管理体系" in content
    assert "本节点须规避的废标项" in content
    assert "安全生产许可证" in content
    # response rule present
    assert "逐条正面响应上述评分点" in content


def test_prompt_includes_project_specifics_and_style() -> None:
    messages = build_node_fill_prompt(
        node_title="施工组织设计",
        project_name="某村庄建设项目",
        requirements={
            "project_location": "长丰县罗塘乡",
            "quality_standard": "合格",
            "safety_target": "无重大事故",
        },
        company_name="安徽正奇建设有限公司",
    )
    content = _user_content(messages)
    # project specifics surfaced for project-specificity
    assert "建设地点：长丰县罗塘乡" in content
    assert "质量目标：合格" in content
    assert "安全目标：无重大事故" in content
    # style/depth directives present
    assert "写作风格与深度" in content
    assert "避免可套用到任何项目的通用空话" in content


def test_prompt_falls_back_when_no_items() -> None:
    messages = build_node_fill_prompt(
        node_title="施工部署",
        project_name="测试项目",
        requirements={},
        company_name="安徽正奇建设有限公司",
    )
    content = _user_content(messages)

    assert "本节点无直接对应评分点" in content
    assert "无直接对应废标项" in content


def test_distribute_items_assigns_to_best_matching_node() -> None:
    titles = ["质量保证措施", "安全文明施工", "施工组织设计"]
    items = [
        SimpleNamespace(title="质量目标与质量保证体系", description="质量检验计划"),
        SimpleNamespace(title="安全文明施工管理", description="安全生产责任制"),
    ]

    mapping = _distribute_requirement_items(titles, items)

    assert any("质量" in i["title"] for i in mapping["质量保证措施"])
    assert any("安全" in i["title"] for i in mapping["安全文明施工"])


def test_distribute_items_uses_catch_all_when_no_overlap() -> None:
    titles = ["施工组织设计", "进度计划"]
    items = [SimpleNamespace(title="环境保护专项", description="扬尘噪声控制")]

    mapping = _distribute_requirement_items(titles, items)

    # No keyword overlap with either title → lands in the catch-all 施工组织设计 node.
    assert mapping["施工组织设计"]
    assert not mapping["进度计划"]


def test_distribute_items_empty_inputs() -> None:
    assert _distribute_requirement_items([], []) == {}
    assert _distribute_requirement_items(["施工组织设计"], []) == {"施工组织设计": []}


def test_build_bid_outline_uses_tender_scan_faithfully() -> None:
    from agents.generator_agent import build_bid_outline
    from schemas.tender import TechnicalOutlineSection, TenderRequirements

    req = TenderRequirements(
        project_name="某项目",
        technical_outline=[
            TechnicalOutlineSection(title="总体施工组织布置及规划", focus_points=["施工部署"]),
            TechnicalOutlineSection(title="工期保证体系及措施"),
            TechnicalOutlineSection(title="附表一 施工总体计划表", is_attachment=True),
        ],
    )
    outline = build_bid_outline(req)
    titles = [s.title for s in outline]
    # 编制要点原样进目录
    assert "总体施工组织布置及规划" in titles
    assert "工期保证体系及措施" in titles
    # 附表收进一个"附表与附图"节的 manual_image_slots,不单独成正文节
    assert "附表一 施工总体计划表" not in titles
    attach_section = next(s for s in outline if "附表" in s.title)
    assert any(slot.title == "附表一 施工总体计划表" for slot in attach_section.manual_image_slots)
    # 不套用硬编码 9 要点模板
    assert "第一章、总体施工组织布置及规划" not in titles


def test_build_bid_outline_minimal_when_no_scan_no_template() -> None:
    from agents.generator_agent import build_bid_outline
    from schemas.tender import TenderRequirements

    # 无 technical_outline、无 bid_template → 最小中性壳,不套 9 要点模板
    outline = build_bid_outline(TenderRequirements(project_name="某项目"))
    assert [s.title for s in outline] == ["施工组织设计"]
    assert outline[0].focus_points  # 带"请按本招标补充"提示


def test_collect_technical_sections_minimal_when_thin() -> None:
    from schemas.tender import TenderRequirements
    from services.v2_generation_service import _collect_technical_sections

    # Thin/generic tender outline → MINIMAL neutral shell, NOT a detailed template.
    req = TenderRequirements(
        project_name="某村庄建设项目",
        format_outline_tree={"technical": [{"title": "一、施工组织设计", "children": []}]},
    )
    sections = _collect_technical_sections(req)
    assert [s["title"] for s in sections] == ["施工组织设计"]
    assert all(s.get("target_chars", 0) > 0 for s in sections)


def test_collect_technical_sections_honors_specific_tender_outline() -> None:
    from schemas.tender import TenderRequirements
    from services.v2_generation_service import _collect_technical_sections

    # A tender that DOES specify real sections → honored as-is, any granularity.
    req = TenderRequirements(
        project_name="某道路项目",
        format_outline_tree={
            "technical": [
                {"title": "路基工程施工方案", "children": []},
                {"title": "路面工程施工方案", "children": []},
            ]
        },
    )
    titles = [s["title"] for s in _collect_technical_sections(req)]
    assert "路基工程施工方案" in titles
    assert "路面工程施工方案" in titles


def test_prompt_includes_section_guidance_and_length() -> None:
    messages = build_node_fill_prompt(
        node_title="质量管理体系与质量保证措施",
        project_name="某项目",
        requirements={},
        company_name="安徽正奇建设有限公司",
        section_guidance="质量目标分解与承诺、三检制、检验批划分与试验频率",
        target_chars=2400,
    )
    content = next(m["content"] for m in messages if m["role"] == "user")
    assert "本节必须覆盖的工程要点" in content
    assert "三检制" in content
    assert "不少于 2400 字" in content


def test_strip_commercial_sections_keeps_technical_org_section() -> None:
    from services.v2_generation_service import _strip_commercial_sections

    md = (
        "## 项目管理机构与岗位职责\n\n项目经理及岗位职责正文。\n\n"
        "## 资格响应\n\n营业执照有效。\n\n"
        "## 质量管理体系与质量保证措施\n\n质量目标正文。"
    )
    out = _strip_commercial_sections(md)
    # canonical technical section must survive the 项目管理机构 commercial keyword
    assert "项目管理机构与岗位职责" in out
    assert "项目经理及岗位职责正文" in out
    # genuine commercial leakage still stripped
    assert "资格响应" not in out
    assert "营业执照有效" not in out
    assert "质量管理体系与质量保证措施" in out
