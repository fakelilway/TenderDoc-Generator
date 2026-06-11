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
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commits += 1

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


def _fake_execute_values(cursor, statement, argslist, template=None, fetch=False):
    cursor.statements.append((statement, list(argslist)))
    rows = []
    for _values in argslist:
        cursor.next_id += 1
        rows.append({"id": cursor.next_id})
    return rows if fetch else None


def _patch_store(monkeypatch, cursor):
    connections = []

    def fake_connect():
        connection = FakeConnection(cursor)
        connections.append(connection)
        return connection

    monkeypatch.setattr(vector_store, "_metadata_index_ready", False)
    monkeypatch.setattr(vector_store, "_connect", fake_connect)
    monkeypatch.setattr(vector_store, "execute_values", _fake_execute_values)
    return connections


def test_format_vector_uses_pgvector_literal(monkeypatch) -> None:
    monkeypatch.setattr(vector_store.settings, "embedding_dimension", 3)

    assert (
        vector_store.format_vector([1.0, 0.5, -0.25])
        == "[1.0000000000,0.5000000000,-0.2500000000]"
    )


def test_store_knowledge_chunks_inserts_document_and_batched_chunks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(vector_store.settings, "embedding_dimension", 3)
    cursor = FakeCursor()
    connections = _patch_store(monkeypatch, cursor)

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
    assert "knowledge_chunks_metadata_gin" in cursor.statements[0][0]
    assert "USING GIN (metadata)" in cursor.statements[0][0]
    assert "INSERT INTO documents" in cursor.statements[1][0]
    insert_statement, argslist = cursor.statements[2]
    assert "INSERT INTO knowledge_chunks" in insert_statement
    assert len(argslist) == 2  # one batched execute_values call for all chunks
    assert all(connection.commits == 1 for connection in connections)


def test_store_knowledge_chunks_allows_evidence_only_document(monkeypatch) -> None:
    cursor = FakeCursor()
    _patch_store(monkeypatch, cursor)

    result = vector_store.store_knowledge_chunks(
        file_name="身份证.jpg",
        file_path="knowledge/id.jpg",
        file_type="jpg",
        chunks=[],
        embedder=lambda texts: [],
        metadata={"indexing_status": "structured_evidence"},
    )

    assert result == {"document_id": 11, "chunk_ids": []}
    assert len(cursor.statements) == 2
    assert "knowledge_chunks_metadata_gin" in cursor.statements[0][0]
    assert "INSERT INTO documents" in cursor.statements[1][0]


def test_metadata_index_is_created_once_per_process(monkeypatch) -> None:
    cursor = FakeCursor()
    _patch_store(monkeypatch, cursor)

    vector_store.ensure_metadata_index()
    vector_store.ensure_metadata_index()

    statements = [statement for statement, _params in cursor.statements]
    assert len(statements) == 1
    assert "CREATE INDEX IF NOT EXISTS knowledge_chunks_metadata_gin" in statements[0]
