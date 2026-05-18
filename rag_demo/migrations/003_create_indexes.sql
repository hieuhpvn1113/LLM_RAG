-- =============================================
-- Migration 003: Tạo tất cả INDEX
-- =============================================

-- [1] B-Tree: doc_id — JOIN/filter theo document
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id
    ON chunks (doc_id);

-- [2] B-Tree: level — Filter Level 2 khi search
CREATE INDEX IF NOT EXISTS idx_chunks_level
    ON chunks (level);

-- [3] Composite: (doc_id, level, seq_no) — Ordered chunks của 1 doc
CREATE INDEX IF NOT EXISTS idx_chunks_doc_level_seq
    ON chunks (doc_id, level, seq_no);

-- [4] Partial B-Tree: parent_id — Lấy child chunks
CREATE INDEX IF NOT EXISTS idx_chunks_parent_id
    ON chunks (parent_id)
    WHERE parent_id IS NOT NULL;

-- [5] Partial B-Tree: prev_id, next_id — Linked list navigation
CREATE INDEX IF NOT EXISTS idx_chunks_prev_id
    ON chunks (prev_id)
    WHERE prev_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_next_id
    ON chunks (next_id)
    WHERE next_id IS NOT NULL;

-- [6] Partial B-Tree: embed_status — Tìm chunks chưa embed
CREATE INDEX IF NOT EXISTS idx_chunks_embed_status
    ON chunks (embed_status)
    WHERE embed_status != 'done';

-- [7] B-Tree: created_at — Sort/pagination
CREATE INDEX IF NOT EXISTS idx_chunks_created_at
    ON chunks (created_at DESC);

-- [8] GIN: keywords JSONB array — Tìm theo keyword
CREATE INDEX IF NOT EXISTS idx_chunks_keywords_gin
    ON chunks USING GIN (keywords);

-- [9] GIN: entities JSONB — Tìm theo entity
CREATE INDEX IF NOT EXISTS idx_chunks_entities_gin
    ON chunks USING GIN (entities);

-- [10] GIN: hypothetical_questions JSONB
CREATE INDEX IF NOT EXISTS idx_chunks_hypo_questions_gin
    ON chunks USING GIN (hypothetical_questions);

-- [11] GIN Full-text search: clean_text (dùng 'simple' để hỗ trợ tiếng Việt)
CREATE INDEX IF NOT EXISTS idx_chunks_clean_text_fts
    ON chunks USING GIN (to_tsvector('simple', COALESCE(clean_text, '')));

-- [12] GIN Full-text search: title + summary
CREATE INDEX IF NOT EXISTS idx_chunks_title_summary_fts
    ON chunks USING GIN (
        to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(summary, ''))
    );

-- ── documents table ────────────────────────────────────────

-- [13] Partial B-Tree: status
CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (status)
    WHERE status != 'ready';

-- [14] B-Tree: created_at
CREATE INDEX IF NOT EXISTS idx_documents_created_at
    ON documents (created_at DESC);

-- ── search_logs table ──────────────────────────────────────

-- [15] B-Tree: created_at
CREATE INDEX IF NOT EXISTS idx_search_logs_created_at
    ON search_logs (created_at DESC);
