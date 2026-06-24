"""AssetResolver 单元测试:必须返回真实 file_path/storage_key,不能只给文件名。"""

from __future__ import annotations

from services import asset_resolver


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


def _row(file_type="jpg"):
    # (id, file_name, file_path, file_type, metadata_json)
    return (
        290,
        "徐志身份证.jpg",
        "knowledge/abc123_徐志身份证.jpg",
        file_type,
        {
            "document_category": "人员证件",
            "certificate_type": "身份证",
            "owner_type": "人员",
            "owner_name": "徐志",
        },
    )


def test_resolve_returns_real_storage_key(monkeypatch) -> None:
    monkeypatch.setattr(asset_resolver, "_connect", lambda: FakeConnection(FakeCursor([_row()])))
    out = asset_resolver.resolve_asset(owner_name="徐志", asset_type="身份证")

    assert out["matched"] is True
    assert out["asset_name"] == "徐志身份证.jpg"
    # 核心验收:必须有真实路径/storage_key,不能只有名字
    assert out["file_path"] == "knowledge/abc123_徐志身份证.jpg"
    assert out["storage_key"] == out["file_path"]
    assert out["file_path"]  # 非空
    assert out["document_id"] == 290
    assert out["mime_type"] == "image/jpeg"
    assert out["owner_name"] == "徐志"
    assert out["asset_type"] == "身份证"


def test_resolve_png_mime(monkeypatch) -> None:
    monkeypatch.setattr(asset_resolver, "_connect", lambda: FakeConnection(FakeCursor([_row("png")])))
    out = asset_resolver.resolve_asset(asset_type="身份证")
    assert out["mime_type"] == "image/png"


def test_resolve_not_matched(monkeypatch) -> None:
    monkeypatch.setattr(asset_resolver, "_connect", lambda: FakeConnection(FakeCursor([])))
    out = asset_resolver.resolve_asset(owner_name="查无此人", asset_type="身份证")
    assert out["matched"] is False
    assert "reason" in out


def test_resolve_requires_some_filter() -> None:
    out = asset_resolver.resolve_asset()
    assert out["matched"] is False


def test_resolve_filters_to_images_only(monkeypatch) -> None:
    cursor = FakeCursor([_row()])
    monkeypatch.setattr(asset_resolver, "_connect", lambda: FakeConnection(cursor))
    asset_resolver.resolve_asset(owner_name="徐志", asset_type="身份证")
    sql, params = cursor.statements[0]
    # 只认图片格式
    assert "lower(file_type) IN" in sql
    assert "jpg" in params and "png" in params


def _idrow(doc_id):
    return (doc_id, f"{doc_id}.jpg", f"knowledge/{doc_id}.jpg", "jpg", {"certificate_type": "身份证", "owner_name": "许明英"})


def test_pick_id_card_prefers_both(monkeypatch) -> None:
    # 候选: 正面(1)/背面(2)/完整版(3) → 只取完整版1张
    monkeypatch.setattr(asset_resolver, "_list_id_card_candidates", lambda name: [_idrow(1), _idrow(2), _idrow(3)])
    monkeypatch.setattr(asset_resolver, "read_asset_bytes", lambda doc_id: b"x")
    # 按调用顺序返回 side: 正面→背面→完整版
    seq = iter([{"side": "front", "name": ""}, {"side": "back", "name": ""}, {"side": "both", "name": "许明英"}])
    monkeypatch.setattr("services.id_card_ocr.classify_id_card", lambda b: next(seq))
    out = asset_resolver.pick_id_card_documents("许明英")
    assert len(out) == 1 and out[0]["side"] == "both"


def test_pick_id_card_falls_back_to_front_back(monkeypatch) -> None:
    # 没有完整版 → 取 正面+背面 各一
    monkeypatch.setattr(asset_resolver, "_list_id_card_candidates", lambda name: [_idrow(1), _idrow(2)])
    monkeypatch.setattr(asset_resolver, "read_asset_bytes", lambda doc_id: b"x")
    seq = iter([{"side": "front", "name": "许明英"}, {"side": "back", "name": ""}])
    monkeypatch.setattr("services.id_card_ocr.classify_id_card", lambda b: next(seq))
    out = asset_resolver.pick_id_card_documents("许明英")
    assert {o["side"] for o in out} == {"front", "back"}
    assert len(out) == 2


def test_read_asset_bytes_delegates(monkeypatch) -> None:
    monkeypatch.setattr(
        asset_resolver, "get_knowledge_document_file_bytes", lambda doc_id: b"\xff\xd8\xff\xe0data"
    )
    assert asset_resolver.read_asset_bytes(290) == b"\xff\xd8\xff\xe0data"
