"""业绩选择:推荐打分 + "只插选中的"过滤 回归测试。"""

from __future__ import annotations

from schemas.tender_spec import PerformanceRequirement
from services import performance_selection_service as ps


def _ledger():
    return [
        {"document_id": 1, "name": "2023年某公路大修工程", "year": "2023", "amount": "977万元", "type": "公路工程"},
        {"document_id": 2, "name": "2018年某老旧项目", "year": "2018", "amount": "120万元", "type": "市政"},
    ]


def test_recommend_scores_year_amount_type_evidence(monkeypatch) -> None:
    monkeypatch.setattr(ps.pa, "list_performance_ledger", lambda: _ledger())
    # 第一个项目有证明扫描,第二个没有
    monkeypatch.setattr(ps.pa, "list_evidence_groups", lambda: {"2023年某公路大修工程": {}})

    req = PerformanceRequirement(since="2022年以来", category="公路工程", min_amount_wan=300)
    recs = ps.recommend_performance(req)

    top = recs[0]
    assert top["name"] == "2023年某公路大修工程"
    assert top["has_evidence"] is True
    assert any("≥2022" in m for m in top["matched"])
    assert any("同类" in m for m in top["matched"])
    # 不达标的排后且记缺口
    low = next(r for r in recs if r["name"] == "2018年某老旧项目")
    assert low["score"] < top["score"]
    assert any("早于" in g or "<" in g or "缺证明" in g for g in low["gaps"])


def test_performance_evidence_only_selected(monkeypatch) -> None:
    """选中模式只插选中的项目,不再全堆。"""
    from services import v2_generation_service as v2

    # 三个项目各一张中标通知书
    rows = [
        (10, "项目甲", "中标通知书", "2023", "0"),
        (11, "项目乙", "中标通知书", "2023", "0"),
        (12, "项目丙", "中标通知书", "2023", "0"),
    ]

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return rows

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    monkeypatch.setattr("rag.vector_store.get_db_connection", lambda: _Conn())

    all_md = v2._performance_evidence_markdown()
    sel_md = v2._performance_evidence_markdown(selected_names=["项目乙"])
    assert all_md.count("knowledge_image") == 3
    assert sel_md.count("knowledge_image") == 1
    assert "项目乙" in sel_md and "项目甲" not in sel_md
