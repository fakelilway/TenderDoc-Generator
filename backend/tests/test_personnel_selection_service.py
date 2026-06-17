from types import SimpleNamespace

from schemas.personnel import BuilderCert, PersonnelMember, PMRequirement
from services.personnel_selection_service import (
    derive_pm_requirement,
    recommend_project_managers,
)


def _item(title: str, description: str = "") -> SimpleNamespace:
    return SimpleNamespace(title=title, description=description)


def test_derive_pm_requirement_extracts_level_specialty_and_b() -> None:
    requirements = SimpleNamespace(
        qualification_list=[
            _item(
                "项目经理资格",
                "项目经理须具备公路工程专业一级注册建造师,并具有有效的安全生产考核合格证书(B类)",
            )
        ],
        technical_score_items=[],
    )
    pm = derive_pm_requirement(requirements)
    assert pm.builder_level == "一级建造师"
    assert pm.builder_specialty == "公路工程"
    assert pm.requires_safety_b is True


def test_derive_pm_requirement_empty_when_unspecified() -> None:
    requirements = SimpleNamespace(
        qualification_list=[_item("企业资质", "具备公路工程施工总承包二级及以上")],
        technical_score_items=[],
    )
    pm = derive_pm_requirement(requirements)
    # "项目经理"未提及 → 不抽企业资质里的等级/专业当成 PM 要求
    assert pm.builder_level == ""
    assert pm.builder_specialty == ""


def test_recommend_ranks_and_filters_by_level() -> None:
    roster = [
        PersonnelMember(
            name="甲",
            builder_certs=[BuilderCert(level="一级建造师", specialty="公路工程")],
            safety_cert_classes=["B"],
            source="台账",
        ),
        PersonnelMember(
            name="乙",
            builder_certs=[BuilderCert(level="二级建造师", specialty="公路工程")],
            source="台账",
        ),
        PersonnelMember(
            name="丙",
            builder_certs=[BuilderCert(level="一级建造师", specialty="市政公用工程")],
            source="台账",
        ),
        PersonnelMember(
            name="丁",
            builder_certs=[BuilderCert(level="一级建造师", specialty="")],
            source="知识库",
        ),
        PersonnelMember(name="戊", title="工程师"),  # 非建造师
    ]
    requirement = PMRequirement(
        builder_level="一级建造师", builder_specialty="公路工程", requires_safety_b=True
    )
    recs = recommend_project_managers(roster, requirement)
    names = [rec.member.name for rec in recs]

    assert "戊" not in names  # 非建造师候选
    assert "乙" not in names  # 二级 < 一级要求 → 硬淘汰
    assert names[0] == "甲"  # 一级+公路+B+台账,分最高
    assert "丙" in names and "丁" in names  # 专业不符/待核验 → 保留但排后
    top = recs[0]
    assert "持安全B证" in top.matched and "专业匹配:公路工程" in top.matched
    # 丁(知识库、未注明专业)应带核验缺口
    ding = next(rec for rec in recs if rec.member.name == "丁")
    assert any("专业待核验" in gap for gap in ding.gaps)
    assert any("知识库" in gap for gap in ding.gaps)
