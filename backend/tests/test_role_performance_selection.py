"""角色业绩勾选(项目经理/总工名下业绩人工多选)的服务层测试。

覆盖:候选按选派人名下取、勾选存对应列、None/[]语义、换人自动清空勾选。
"""
from typing import Any

from services import project_service
from services.project import performance as perf_mod
from services.project import personnel as pers_mod


def _record(i: int, manager: str = "李刚", tech: str = "") -> dict:
    return {
        "project_name": f"测试业绩{i}号工程",
        "project_type": "公路工程",
        "project_year": 2020 + i,
        "amount_wan": 100.0 * i,
        "contract_price": f"{i}000000元",
        "project_manager": manager,
        "tech_leader": tech,
        "document_id": i,
    }


class _Cur:
    """假游标:按序吐 fetchone 结果,记录 execute 的 SQL/参数。"""

    def __init__(self, rows: list[Any]):
        self._rows = list(rows)
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> Any:
        return self._rows.pop(0) if self._rows else None

    def __enter__(self) -> "_Cur":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _Conn:
    def __init__(self, cur: _Cur):
        self._cur = cur

    def cursor(self, cursor_factory: Any = None) -> _Cur:
        return self._cur

    def __enter__(self) -> "_Conn":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def test_recommend_role_performance_lists_person_records(monkeypatch) -> None:
    """选派了总工许明英 → 候选=她名下(tech_leader)记录,带证明标记;selected 原样透传。"""
    monkeypatch.setattr(
        perf_mod,
        "_fetch_project",
        lambda pid: {
            "selected_personnel": {"tech_director": {"name": "许明英"}},
            "selected_td_performance": None,  # 没勾过
        },
    )
    from services import similar_project_info_service as spi

    monkeypatch.setattr(
        spi, "records_for_tech_leader",
        lambda name: [_record(1, tech=name), _record(2, tech=name)] if name == "许明英" else [],
    )
    from services import performance_archive_service as pa

    monkeypatch.setattr(pa, "list_evidence_groups", lambda: {"测试业绩1号工程": []})

    res = perf_mod.recommend_role_performance(7, "td")
    assert res["person"] == "许明英"
    assert res["selected"] is None  # 没勾过(全部人工手选,前端一条不预勾)
    names = [r["name"] for r in res["recommendations"]]
    assert names == ["测试业绩1号工程", "测试业绩2号工程"]
    assert res["recommendations"][0]["has_evidence"] is True
    assert res["recommendations"][0]["matched"] == ["有证明扫描"]
    assert res["recommendations"][1]["gaps"] == ["缺证明扫描"]


def test_recommend_role_performance_without_person(monkeypatch) -> None:
    """该角色尚未选派 → person=None、候选为空(前端提示先选派)。"""
    monkeypatch.setattr(
        perf_mod, "_fetch_project", lambda pid: {"selected_personnel": {}}
    )
    res = perf_mod.recommend_role_performance(7, "pm")
    assert res["person"] is None
    assert res["recommendations"] == []


def test_recommend_role_performance_lists_role_holders(monkeypatch) -> None:
    """响应带 role_holders(信息表里当过该角色的人+条数):选了47表外的人时,
    面板要能告诉用户"谁有业绩可选"(凌雨实测困惑)。"""
    monkeypatch.setattr(
        perf_mod,
        "_fetch_project",
        lambda pid: {"selected_personnel": {"tech_director": {"name": "凌雨"}}},
    )
    from services import similar_project_info_service as spi

    monkeypatch.setattr(spi, "records_for_tech_leader", lambda name: [])
    monkeypatch.setattr(
        spi,
        "list_similar_project_records",
        lambda: [
            {"project_name": f"工程{i}", "tech_leader": "许明英", "project_manager": "李刚"}
            for i in range(3)
        ] + [{"project_name": "工程x", "tech_leader": "赵勇", "project_manager": "李刚"}],
    )
    res = perf_mod.recommend_role_performance(7, "td")
    assert res["person"] == "凌雨"
    assert res["recommendations"] == []
    assert res["role_holders"][0] == {"name": "许明英", "count": 3}
    assert {"name": "赵勇", "count": 1} in res["role_holders"]


def test_save_selected_role_performance_writes_role_column(monkeypatch) -> None:
    """保存经理勾选 → 写 selected_pm_performance 列,条目清洗成5键。"""
    cur = _Cur([{"id": 7, "selected_pm_performance": [{"name": "测试业绩1号工程"}]}])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur))

    res = perf_mod.save_selected_role_performance(
        7, "pm", [{"name": "测试业绩1号工程", "year": "2021", "extra": "丢弃"}, {"name": ""}]
    )
    sql, params = cur.executed[0]
    assert "selected_pm_performance" in sql
    clean = params[0].adapted  # psycopg2 Json 包装的原值
    assert clean == [
        {"name": "测试业绩1号工程", "year": "2021", "amount": "", "type": "", "document_id": None}
    ]
    assert res["role"] == "pm"
    assert res["selected"] == [{"name": "测试业绩1号工程"}]


def test_save_selected_role_performance_rejects_bad_role() -> None:
    import pytest

    with pytest.raises(ValueError):
        perf_mod.save_selected_role_performance(7, "boss", [])


def test_changing_person_resets_role_performance(monkeypatch) -> None:
    """换项目经理 → selected_pm_performance 一并重置为 NULL;同人重存则不动勾选。"""
    # 换人:李刚 → 王露
    cur = _Cur([
        {"selected_personnel": {"project_manager": {"name": "李刚"}}},
        {"id": 7, "selected_personnel": {"project_manager": {"name": "王露"}}},
    ])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur))
    pers_mod.save_selected_project_manager(7, {"name": "王露"})
    update_sql = cur.executed[1][0]
    assert "selected_pm_performance = NULL" in update_sql

    # 同人重存:不清勾选
    cur2 = _Cur([
        {"selected_personnel": {"project_manager": {"name": "王露"}}},
        {"id": 7, "selected_personnel": {"project_manager": {"name": "王露"}}},
    ])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur2))
    pers_mod.save_selected_project_manager(7, {"name": "王露"})
    assert "selected_pm_performance" not in cur2.executed[1][0]

    # 清空选派:也要清勾选
    cur3 = _Cur([
        {"selected_personnel": {"tech_director": {"name": "许明英"}}},
        {"id": 7, "selected_personnel": {}},
    ])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur3))
    pers_mod.save_selected_tech_director(7, None)
    assert "selected_td_performance = NULL" in cur3.executed[1][0]
