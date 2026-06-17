from rag import retriever
from rag.retriever import RetrievalResult


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statement = statement
        self.params = params

    def fetchall(self):
        return [
            (
                1,
                2,
                "高层住宅施工组织设计方案",
                {"source_path": "a.txt"},
                0.1,
            ),
            (2, 2, "企业资质证书", {"source_path": "b.txt"}, 0.2),
        ]


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor()


def test_retrieve_returns_ranked_results(monkeypatch) -> None:
    monkeypatch.setattr(retriever, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(retriever, "embed_text", lambda query: [1.0, 0.0, 0.0])
    monkeypatch.setattr(retriever, "format_vector", lambda vector: "[1,0,0]")

    results = retriever.retrieve("高层住宅施工组织设计", top_k=2)

    assert results[0].content == "高层住宅施工组织设计方案"
    assert results[0].score > results[1].score


def test_cross_encoder_is_loaded_once_per_model_name(monkeypatch) -> None:
    instantiations = []

    class FakeCrossEncoder:
        def __init__(self, model_name):
            instantiations.append(model_name)

        def predict(self, pairs):
            return [float(len(pairs) - index) for index in range(len(pairs))]

    monkeypatch.setattr(retriever, "CrossEncoder", FakeCrossEncoder)
    monkeypatch.setattr(retriever, "_cross_encoder_cache", {})
    results = [
        RetrievalResult(1, 1, "施工组织设计", {}, 0.1, 0.9),
        RetrievalResult(2, 1, "企业资质证书", {}, 0.2, 0.8),
    ]

    first = retriever.rerank_with_cross_encoder("施工组织设计", results, "bge-reranker")
    second = retriever.rerank_with_cross_encoder("施工组织设计", results, "bge-reranker")

    assert instantiations == ["bge-reranker"]
    assert [result.chunk_id for result in first] == [1, 2]
    assert [result.chunk_id for result in second] == [1, 2]


class CapturingCursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.sink["sql"] = statement
        self.sink["params"] = params

    def fetchall(self):
        return []


class CapturingConnection:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return CapturingCursor(self.sink)


def _capture_retrieve(monkeypatch, **kwargs):
    sink: dict = {}
    monkeypatch.setattr(retriever, "_connect", lambda: CapturingConnection(sink))
    monkeypatch.setattr(retriever, "embed_text", lambda query: [1.0, 0.0, 0.0])
    monkeypatch.setattr(retriever, "format_vector", lambda vector: "[1,0,0]")
    retriever.retrieve_filtered(query="施工组织设计", top_k=3, **kwargs)
    return sink


def test_retrieve_is_global_only_without_project_id(monkeypatch) -> None:
    # 默认(全局检索/搜索):只看全局库,绝不漏出任何项目专用材料。
    sink = _capture_retrieve(monkeypatch)
    assert "metadata->>'project_id' IS NULL" in sink["sql"]
    assert "metadata->>'project_id' = %s" not in sink["sql"]


def test_retrieve_unions_project_material_and_global(monkeypatch) -> None:
    # M23 grounding:传 project_id → 本项目专用材料 ∪ 全局库。
    sink = _capture_retrieve(monkeypatch, project_id=123)
    assert (
        "(metadata->>'project_id' = %s OR metadata->>'project_id' IS NULL)"
        in sink["sql"]
    )
    assert "123" in sink["params"]


def test_retrieve_explicit_chunk_ids_bypass_project_scope(monkeypatch) -> None:
    # 用户按 id 钦点的 chunk 是权威的,不再叠 project 过滤(否则会把选中的项目材料过滤掉)。
    sink = _capture_retrieve(monkeypatch, chunk_ids=[5, 6], project_id=123)
    assert "id = ANY(%s)" in sink["sql"]
    assert "metadata->>'project_id'" not in sink["sql"]
    assert [5, 6] in sink["params"]


def test_keyword_rerank_promotes_overlap() -> None:
    results = [
        RetrievalResult(1, 1, "无关内容", {}, 0.01, 0.99),
        RetrievalResult(2, 1, "高层住宅施工组织设计", {}, 0.2, 0.83),
    ]

    reranked = retriever.rerank_by_keyword_overlap("高层住宅施工组织设计", results)

    assert reranked[0].chunk_id == 2
