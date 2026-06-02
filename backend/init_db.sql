CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    tender_file_path TEXT,
    parsed_json JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT REFERENCES projects(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT,
    file_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE documents ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE VECTOR(1024);

CREATE INDEX IF NOT EXISTS idx_documents_project_id ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING ivfflat (embedding vector_l2_ops)
    WITH (lists = 100);
