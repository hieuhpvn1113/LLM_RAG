-- =============================================
-- Migration 001: Tạo bảng documents
-- =============================================
CREATE TABLE IF NOT EXISTS documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name       TEXT NOT NULL,
    file_path       TEXT,
    total_chunks    INTEGER DEFAULT 0,
    total_sections  INTEGER DEFAULT 0,
    file_size_bytes BIGINT,
    mime_type       TEXT DEFAULT 'text/plain',
    status          TEXT DEFAULT 'processing'
                    CHECK (status IN ('processing', 'ready', 'error')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
