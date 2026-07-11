"""业绩保底入选测试:信息表里真带过项目的经理/总工不许被硬性门槛藏起来。

背景(项目200实测):招标要总工高级职称,许明英(工程师职称)带过15个项目的总工却
整个从候选列表消失。规矩改为:带过项目的人保底入选+挂"废标风险,慎选"警告+按
项目数加分;没带过的仍按原硬性门槛淘汰(行为不变)。
"""
from schemas.personnel import BuilderCert, PersonnelMember, PMRequirement, TechDirectorRequirement
from services.personnel_selection_service import (
    recommend_project_managers,
    recommend_tech_directors,
)


def _member(name: str, title: str = "", certs: list | None = None) -> PersonnelMember:
    return PersonnelMember(name=name, title=title, builder_certs=certs or [], source="台账")


def test_proven_td_below_title_requirement_kept_with_warning() -> None:
    """招标要高级职称:没带过项目的工程师淘汰(原行为);带过15项的许明英保底入选+警告。"""
    req = TechDirectorRequirement(title_level="高级职称")
    roster = [
        _member("许明英", title="工程师"),
        _member("路人甲", title="工程师"),
        _member("赵勇", title="高级工程师"),
    ]
    recs = recommend_tech_directors(roster, req, performance_counts={"许明英": 15})
    names = [r.member.name for r in recs]
    assert "许明英" in names  # 保底入选
    assert "路人甲" not in names  # 无业绩背书,原硬性门槛照旧
    xu = next(r for r in recs if r.member.name == "许明英")
    assert any("废标风险" in g for g in xu.gaps)
    assert any("当过15个项目的技术负责人" in m for m in xu.matched)
    # 职称达标者仍排在保底者前面
    assert names.index("赵勇") < names.index("许明英")


def test_proven_pm_without_cert_or_below_level_kept() -> None:
    """经理侧同理:无建造师证/等级不够但带过项目→保底入选带警告;没带过→淘汰。"""
    req = PMRequirement(builder_level="一级建造师")
    roster = [
        _member("有证达标", certs=[BuilderCert(level="一级建造师", specialty="公路工程")]),
        _member("二级带过项目", certs=[BuilderCert(level="二级建造师")]),
        _member("二级没带过", certs=[BuilderCert(level="二级建造师")]),
        _member("无证带过项目"),
    ]
    recs = recommend_project_managers(
        roster, req, performance_counts={"二级带过项目": 3, "无证带过项目": 2}
    )
    names = [r.member.name for r in recs]
    assert "二级带过项目" in names and "无证带过项目" in names
    assert "二级没带过" not in names  # 原硬性淘汰不变
    lv = next(r for r in recs if r.member.name == "二级带过项目")
    assert any("废标风险" in g for g in lv.gaps)
    nocert = next(r for r in recs if r.member.name == "无证带过项目")
    assert any("保底入选" in g for g in nocert.gaps)
    assert names[0] == "有证达标"  # 达标者仍在最前


def test_proven_candidates_survive_top_n_cutoff() -> None:
    """名册人多时,带过项目的人分不够也不许被前N名截掉(追加在尾部)。"""
    req = TechDirectorRequirement(title_level="高级职称")
    roster = [
        _member(f"高工{i:02d}", title="高级工程师") for i in range(25)
    ] + [_member("许明英", title="工程师")]
    recs = recommend_tech_directors(
        roster, req, limit=20, performance_counts={"许明英": 15}
    )
    names = [r.member.name for r in recs]
    assert "许明英" in names  # 分数排不进前20也必须在列表里
    assert len(names) == 21  # 前20 + 业绩保底1人


def test_performance_bonus_ranks_proven_first() -> None:
    """条件相同时,带过项目的人排在没带过的前面(业绩加分)。"""
    req = PMRequirement()  # 不限
    roster = [
        _member("没带过", certs=[BuilderCert(level="二级建造师", specialty="公路工程")]),
        _member("带过五项", certs=[BuilderCert(level="二级建造师", specialty="公路工程")]),
    ]
    recs = recommend_project_managers(roster, req, performance_counts={"带过五项": 5})
    assert [r.member.name for r in recs] == ["带过五项", "没带过"]
    assert any("当过5个项目的项目经理" in m for m in recs[0].matched)
