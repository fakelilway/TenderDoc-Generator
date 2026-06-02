from agents import generator_agent
from schemas.tender import RequirementItem, TenderRequirements


def _requirements() -> TenderRequirements:
    return TenderRequirements(
        project_name="星河湾二期高层住宅施工总承包项目",
        qualification_list=[RequirementItem(title="企业资质", description="建筑工程施工总承包一级")],
        technical_score_items=[
            RequirementItem(title="施工组织设计", description="施工组织设计 30 分"),
            RequirementItem(title="质量保证措施", description="质量保证措施 10 分"),
            RequirementItem(title="工期计划", description="进度计划 10 分"),
        ],
        invalid_bid_items=[RequirementItem(title="无效投标", description="未提交保证金按无效投标处理")],
    )


def test_build_bid_outline_uses_technical_score_items() -> None:
    outline = generator_agent.build_bid_outline(_requirements())
    titles = [section.title for section in outline]

    assert "施工组织设计" in titles
    assert "质量保证措施" in titles
    assert "进度计划与工期保证" in titles


def test_build_bid_outline_changes_with_input() -> None:
    requirements = TenderRequirements(
        technical_score_items=[
            RequirementItem(title="安全文明施工", description="安全文明施工 15 分")
        ]
    )

    outline = generator_agent.build_bid_outline(requirements)

    assert outline[0].title == "安全文明施工措施"


def test_generate_bid_section_fallback_has_markdown_and_no_placeholder(monkeypatch):
    monkeypatch.setattr(
        generator_agent,
        "_generate_section_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    markdown = generator_agent.generate_bid_section(
        "施工组织设计",
        _requirements(),
        ["类似高层住宅项目施工组织设计经验。"],
    )

    assert markdown.startswith("## 施工组织设计")
    assert "星河湾二期" in markdown
    assert "待补充" not in markdown
