from rag.indexer import KnowledgeChunk
from rag import vector_store


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.next_id = 10

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        self.next_id += 1
        return {"id": self.next_id}


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


def test_format_vector_uses_pgvector_literal(monkeypatch) -> None:
    monkeypatch.setattr(vector_store.settings, "embedding_dimension", 3)

    assert (
        vector_store.format_vector([1.0, 0.5, -0.25])
        == "[1.0000000000,0.5000000000,-0.2500000000]"
    )


def test_store_knowledge_chunks_inserts_document_and_chunks(monkeypatch) -> None:
    monkeypatch.setattr(vector_store.settings, "embedding_dimension", 3)
    cursor = FakeCursor()
    monkeypatch.setattr(vector_store, "_connect", lambda: FakeConnection(cursor))

    result = vector_store.store_knowledge_chunks(
        file_name="知识.txt",
        file_path="knowledge/file.txt",
        file_type="txt",
        chunks=[
            KnowledgeChunk("施工组织设计", {"chunk_index": 0}),
            KnowledgeChunk("高层住宅业绩", {"chunk_index": 1}),
        ],
        embedder=lambda texts: [[1.0, 0.0, 0.0] for _text in texts],
    )

    assert result == {"document_id": 11, "chunk_ids": [12, 13]}
    assert len(cursor.statements) == 3
    assert "INSERT INTO documents" in cursor.statements[0][0]
    assert "INSERT INTO knowledge_chunks" in cursor.statements[1][0]


def test_store_knowledge_chunks_allows_evidence_only_document(monkeypatch) -> None:
    cursor = FakeCursor()
    monkeypatch.setattr(vector_store, "_connect", lambda: FakeConnection(cursor))

    result = vector_store.store_knowledge_chunks(
        file_name="身份证.jpg",
        file_path="knowledge/id.jpg",
        file_type="jpg",
        chunks=[],
        embedder=lambda texts: [],
        metadata={"indexing_status": "structured_evidence"},
    )

    assert result == {"document_id": 11, "chunk_ids": []}
    assert len(cursor.statements) == 1
    assert "INSERT INTO documents" in cursor.statements[0][0]
