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


def test_keyword_rerank_promotes_overlap() -> None:
    results = [
        RetrievalResult(1, 1, "无关内容", {}, 0.01, 0.99),
        RetrievalResult(2, 1, "高层住宅施工组织设计", {}, 0.2, 0.83),
    ]

    reranked = retriever.rerank_by_keyword_overlap("高层住宅施工组织设计", results)

    assert reranked[0].chunk_id == 2
