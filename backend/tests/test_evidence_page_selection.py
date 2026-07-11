"""业绩证明选页(员工意见7)测试:页清单/默认规则/存取语义/生成侧绕开每类上限。"""
from typing import Any

from services import project_service
from services.project import performance as perf_mod


class _Cur:
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


def _groups():
    """一个项目:中标1张 + 交工验收6张(盖章页排第6,默认规则会截掉)。"""
    return {
        "251#测试养护工程": {
            "evidence": {
                "交工验收": [
                    {"document_id": 100 + i, "file_name": f"交工验收_{i}.jpg",
                     "evidence_type": "交工验收", "evidence_seq": i}
                    for i in range(1, 7)
                ],
                "中标通知书": [
                    {"document_id": 11, "file_name": "中标通知书.jpg",
                     "evidence_type": "中标通知书", "evidence_seq": 1}
                ],
            },
            "total": 7,
        }
    }


def test_page_options_orders_types_and_caps_default(monkeypatch) -> None:
    """页按 中标→合同→交工 排;默认规则交工只取前4(第5/6张不在 default_ids)。"""
    from services import performance_archive_service as pa

    monkeypatch.setattr(perf_mod, "_fetch_project", lambda pid: {})
    monkeypatch.setattr(pa, "list_evidence_groups", _groups)

    res = perf_mod.get_evidence_page_options(7, "测试养护工程")  # 名字差序号前缀,靠归一化对上
    types = [p["evidence_type"] for p in res["pages"]]
    assert types == ["中标通知书"] + ["交工验收"] * 6
    assert res["default_ids"] == [11, 101, 102, 103, 104]  # 交工只默认前4
    assert res["selected"] is None


def test_page_options_reads_stored_selection_by_norm(monkeypatch) -> None:
    """已存选页(键名写法有出入)按归一化名也能读回。"""
    from services import performance_archive_service as pa

    monkeypatch.setattr(
        perf_mod,
        "_fetch_project",
        lambda pid: {"selected_evidence_pages": {"251#测试养护工程": [11, 106]}},
    )
    monkeypatch.setattr(pa, "list_evidence_groups", _groups)
    res = perf_mod.get_evidence_page_options(7, "测试养护工程")
    assert res["selected"] == [11, 106]


def test_save_evidence_pages_merge_and_reset(monkeypatch) -> None:
    """保存=读改写单键(留别的业绩的选页);None=删键恢复默认;id 清洗成 int。"""
    cur = _Cur([
        {"selected_evidence_pages": {"别的工程": [1]}},
        {"id": 7, "selected_evidence_pages": {"别的工程": [1], "测试工程": [11, 106]}},
    ])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur))
    res = perf_mod.save_evidence_page_selection(7, "测试工程", [11, "106", "垃圾"])
    payload = cur.executed[1][1][0].adapted
    assert payload == {"别的工程": [1], "测试工程": [11, 106]}
    assert res["selected"] == [11, 106]

    cur2 = _Cur([
        {"selected_evidence_pages": {"测试工程": [11]}},
        {"id": 7, "selected_evidence_pages": {}},
    ])
    monkeypatch.setattr(project_service, "_connect", lambda: _Conn(cur2))
    res2 = perf_mod.save_evidence_page_selection(7, "测试工程", None)
    assert cur2.executed[1][1][0].adapted == {}
    assert res2["selected"] is None


def test_builder_page_selection_bypasses_cap_and_skips_cleared() -> None:
    """选了页:第6张交工(盖章页)也进;没勾的默认页被去掉。空列表=该业绩整组不出。"""
    from services.v2_generation_service import _build_performance_evidence_md

    rows = [(11, "251#测试养护工程", "中标通知书", "2023", 1)] + [
        (100 + i, "251#测试养护工程", "交工验收", "2023", i) for i in range(1, 7)
    ]
    from services.performance_archive_service import _norm

    key = _norm("251#测试养护工程")
    md = _build_performance_evidence_md(
        rows, limit_projects=6, page_selection={key: [11, 106]}
    )
    assert "document_id=106" in md  # 盖章页(第6张)进了
    assert "document_id=101" not in md  # 默认会取的第1张没勾,不出
    assert md.count("document_id=") == 2

    md_cleared = _build_performance_evidence_md(
        rows, limit_projects=6, page_selection={key: []}
    )
    assert md_cleared == ""  # 全不勾,该业绩不附图

    md_default = _build_performance_evidence_md(rows, limit_projects=6)
    assert md_default.count("document_id=") == 5  # 默认:中标1+交工前4
    assert "document_id=106" not in md_default


def test_evidence_page_selection_maps_norm_keys(monkeypatch) -> None:
    """_evidence_page_selection 键归一化;project_id=None/读失败返回空(走默认)。"""
    from services import v2_generation_service as v2
    from services.performance_archive_service import _norm

    monkeypatch.setattr(
        project_service,
        "_fetch_project",
        lambda pid: {"selected_evidence_pages": {"251#测试养护工程": [11, "106"]}},
    )
    sel = v2._evidence_page_selection(7)
    assert sel == {_norm("251#测试养护工程"): [11, 106]}
    assert v2._evidence_page_selection(None) == {}
