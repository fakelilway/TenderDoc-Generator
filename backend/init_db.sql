CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id BIGINT,
    tender_file_path TEXT,
    parsed_json JSONB,
    generated_markdown_path TEXT,
    generated_docx_path TEXT,
    generation_quality_json JSONB,
    review_report_json JSONB,
    workflow_state_json JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    can_view_knowledge BOOLEAN NOT NULL DEFAULT FALSE,
    can_edit_knowledge BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS registration_codes (
    id BIGSERIAL PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    created_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    used_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projects ADD COLUMN IF NOT EXISTS generated_markdown_path TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS generated_docx_path TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS generation_quality_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS review_report_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS workflow_state_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS confirmed_parsed_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS bid_outline_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS document_outline_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS selected_chunk_ids JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS edited_markdown TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS final_checklist_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS final_versions_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS pricing_strategy_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS pricing_strategy_report_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS score_prediction_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS response_matrix_json JSONB;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS bid_templates (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source_filename TEXT,
    project_type TEXT,
    specialty TEXT,
    envelope_type TEXT,
    region TEXT,
    project_year INT,
    tags JSONB,
    template_json JSONB NOT NULL,
    created_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projects ADD COLUMN IF NOT EXISTS template_id BIGINT REFERENCES bid_templates(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_knowledge BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_edit_knowledge BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE users
SET can_view_knowledge = TRUE,
    can_edit_knowledge = TRUE
WHERE role = 'admin';

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
ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata_json JSONB;
ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE VECTOR(1024);

CREATE INDEX IF NOT EXISTS idx_projects_owner_user_id ON projects(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_projects_template_id ON projects(template_id);
CREATE INDEX IF NOT EXISTS idx_bid_templates_project_type ON bid_templates(project_type);
CREATE INDEX IF NOT EXISTS idx_documents_project_id ON documents(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users (LOWER(username));
CREATE INDEX IF NOT EXISTS idx_registration_codes_expires_at ON registration_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING ivfflat (embedding vector_l2_ops)
    WITH (lists = 100);
