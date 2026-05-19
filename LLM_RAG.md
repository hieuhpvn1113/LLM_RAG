# 🧠 Plan: Hệ thống RAG thông minh — Vector + Keyword + Graph DB

> **Mục tiêu:** Demo/Test hệ thống lưu trữ và tìm kiếm dữ liệu thông minh bằng AI
> **Input:** File text do người dùng cung cấp
> **Output:** Câu trả lời chính xác từ LLM dựa trên dữ liệu thật
> **Cập nhật:** 2025-05

---

## 1. Lựa chọn 3 DB phổ biến nhất (2025)

| Vai trò | DB chọn | Lý do |
|---|---|---|
| **Vector DB** | **Qdrant** | Open-source, viết bằng Rust, nhanh nhất trong benchmark, native hybrid search (dense + sparse), dễ chạy local bằng Docker, API Python đơn giản. Dùng bởi Canva, Tripadvisor, OpenTable |
| **Keyword DB** | **Elasticsearch** | Số 1 về full-text search, BM25 mạnh nhất, ecosystem lớn nhất, hỗ trợ hybrid search kết hợp vector, mature nhất thị trường |
| **Graph DB** | **Neo4j** | Số 1 graph DB thế giới, Cypher query đơn giản, có Community Edition miễn phí, tích hợp tốt với Python, được dùng bởi Microsoft/GraphRAG |
| **Meta/Relational DB** | **PostgreSQL** | Mạnh mẽ, production-ready, hỗ trợ JSONB, Full-text search tích hợp, indexing phong phú (B-Tree, GIN, GiST, Hash), thay thế SQLite để scale tốt hơn |

---

## 2. Cấu trúc thư mục dự án

```
rag_demo/
│
├── data/                          # Dữ liệu đầu vào
│   └── input.txt                  # File text người dùng copy vào đây
│
├── core/                          # Logic chính
│   ├── __init__.py
│   ├── chunker.py                 # Semantic + Hierarchical chunking
│   ├── enricher.py                # LLM enrichment (title, summary, keywords, hypothetical Q)
│   ├── embedder.py                # Tạo vector embedding
│   ├── ingestor.py                # Điều phối toàn bộ pipeline ingest
│   └── retriever.py               # Search 3 DB + RRF merge + rerank
│
├── db/                            # Kết nối database
│   ├── __init__.py
│   ├── meta_db.py                 # PostgreSQL — Meta Table quản lý chunk_id
│   ├── vector_db.py               # Qdrant client
│   ├── keyword_db.py              # Elasticsearch client
│   └── graph_db.py                # Neo4j client
│
├── llm/                           # Tương tác với LLM
│   ├── __init__.py
│   ├── client.py                  # Anthropic Claude API client
│   └── prompts.py                 # Tất cả prompt templates
│
├── api/                           # (Optional) REST API đơn giản
│   └── main.py                    # FastAPI server
│
├── migrations/                    # SQL migration files
│   ├── 001_create_documents.sql
│   ├── 002_create_chunks.sql
│   └── 003_create_indexes.sql     # Tất cả INDEX definitions
│
├── config.py                      # Cấu hình toàn bộ hệ thống
├── main.py                        # Entry point — chạy demo
├── requirements.txt
└── docker-compose.yml             # Khởi động Qdrant + Elasticsearch + Neo4j + PostgreSQL
```

---

## 3. Cấu trúc Meta Table — PostgreSQL

> **Thay SQLite bằng PostgreSQL** để có: transaction mạnh hơn, indexing phong phú hơn (GIN, GiST), JSONB support, scale tốt hơn khi data lớn.

### 3.1 Schema SQL

```sql
-- =============================================
-- BẢNG: documents — quản lý tài liệu gốc
-- =============================================
CREATE TABLE documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name       TEXT NOT NULL,
    file_path       TEXT,
    total_chunks    INTEGER DEFAULT 0,
    total_sections  INTEGER DEFAULT 0,
    file_size_bytes BIGINT,
    mime_type       TEXT DEFAULT 'text/plain',
    status          TEXT DEFAULT 'processing'  -- processing | ready | error
                    CHECK (status IN ('processing', 'ready', 'error')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- BẢNG: chunks — đơn vị tìm kiếm trung tâm
-- =============================================
CREATE TABLE chunks (
    -- Định danh
    chunk_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id      UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,

    -- Phân cấp cha/con (Hierarchical)
    level       SMALLINT NOT NULL CHECK (level IN (0, 1, 2)),
                -- 0 = document summary
                -- 1 = section  (Level 1 — ~800-1200 token)
                -- 2 = paragraph (Level 2 — ~300-512 token, đây là unit embed)
    parent_id   UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    prev_id     UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    next_id     UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    seq_no      INTEGER NOT NULL DEFAULT 0,     -- Thứ tự trong document

    -- Nội dung
    raw_text    TEXT NOT NULL,                  -- Văn bản gốc chưa clean
    clean_text  TEXT,                           -- Sau khi remove noise
    title       TEXT,                           -- LLM tạo ra
    summary     TEXT,                           -- LLM tóm tắt 2-3 câu

    -- Enrichment từ LLM (dạng JSONB để query linh hoạt)
    keywords            JSONB DEFAULT '[]',     -- ["keyword1", "keyword2", ...]
    entities            JSONB DEFAULT '[]',     -- [{"name": "...", "type": "PERSON"}, ...]
    hypothetical_questions JSONB DEFAULT '[]',  -- ["câu hỏi 1", "câu hỏi 2", ...]
    relations           JSONB DEFAULT '[]',     -- [{"from": "A", "relation": "...", "to": "B"}]

    -- Metadata kỹ thuật
    token_count     INTEGER,
    source_file     TEXT,
    page_no         INTEGER,
    char_start      INTEGER,    -- Vị trí ký tự bắt đầu trong file gốc
    char_end        INTEGER,    -- Vị trí ký tự kết thúc
    embed_model     TEXT,       -- Model đã dùng để embed (để track version)
    embed_status    TEXT DEFAULT 'pending'
                    CHECK (embed_status IN ('pending', 'done', 'error')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- BẢNG: search_logs — log mọi query để phân tích
-- =============================================
CREATE TABLE search_logs (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_original  TEXT NOT NULL,
    query_rewritten JSONB,                  -- 3 phiên bản rewrite
    chunks_retrieved JSONB,                 -- chunk_ids + scores sau RRF
    llm_response    TEXT,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. Xây dựng INDEX — Chi tiết và Lý giải

> **Index là then chốt để PostgreSQL trả kết quả nhanh.** Không có index, mỗi query phải scan toàn bộ bảng (Sequential Scan). Với hàng nghìn chunks, điều đó rất chậm.

### 4.1 Các loại Index PostgreSQL dùng trong dự án này

| Loại Index | Dùng cho | Lý do chọn |
|---|---|---|
| **B-Tree** | Cột UUID, TEXT, INTEGER, TIMESTAMPTZ | Default, tốt nhất cho `=`, `<`, `>`, `ORDER BY` |
| **GIN** | Cột JSONB (`keywords`, `entities`, `hypothetical_questions`) | Tốt nhất cho tìm kiếm trong JSON array/object |
| **GIN (tsvector)** | Full-text search trên `clean_text`, `title` | Cho phép `@@` operator tìm text tự nhiên |
| **Hash** | Cột UUID khi chỉ dùng `=` | Nhanh hơn B-Tree cho equality-only lookup |
| **Partial Index** | Lọc theo điều kiện cố định | Nhỏ hơn, nhanh hơn full index |

---

### 4.2 INDEX cho bảng `chunks` — Đầy đủ

```sql
-- =============================================
-- FILE: migrations/003_create_indexes.sql
-- =============================================

-- [1] B-Tree trên doc_id — JOIN và filter theo document
--     Query: SELECT * FROM chunks WHERE doc_id = '...'
CREATE INDEX idx_chunks_doc_id
    ON chunks (doc_id);
-- Lý do: Mỗi lần ingest hoặc xóa document, cần tìm tất cả chunks của doc đó
-- Kiểu: B-Tree (default) — tốt cho equality lookup + range scan

-- [2] B-Tree trên level — Filter chỉ lấy Level 2 khi search
--     Query: SELECT * FROM chunks WHERE level = 2
CREATE INDEX idx_chunks_level
    ON chunks (level);
-- Lý do: Khi search chỉ tìm Level 2 (paragraph), không muốn scan Level 0/1
-- Kiểu: B-Tree

-- [3] Composite Index (doc_id, level, seq_no) — Lấy ordered chunks của 1 document
--     Query: SELECT * FROM chunks WHERE doc_id = '...' AND level = 2 ORDER BY seq_no
CREATE INDEX idx_chunks_doc_level_seq
    ON chunks (doc_id, level, seq_no);
-- Lý do: Khi rebuild context hoặc export toàn bộ chunks của 1 document theo thứ tự
-- Composite index tránh sort thêm, PostgreSQL dùng index scan trực tiếp

-- [4] B-Tree trên parent_id — Lấy child chunks của 1 section
--     Query: SELECT * FROM chunks WHERE parent_id = '...'
CREATE INDEX idx_chunks_parent_id
    ON chunks (parent_id)
    WHERE parent_id IS NOT NULL;  -- Partial index: bỏ qua root chunks
-- Lý do: Context expand cần lấy tất cả paragraph con của 1 section
-- Partial index: nhỏ hơn vì bỏ Level 0/1 không có parent

-- [5] B-Tree trên prev_id, next_id — Duyệt linked list
--     Query: SELECT * FROM chunks WHERE prev_id = '...' OR next_id = '...'
CREATE INDEX idx_chunks_prev_id ON chunks (prev_id) WHERE prev_id IS NOT NULL;
CREATE INDEX idx_chunks_next_id ON chunks (next_id) WHERE next_id IS NOT NULL;
-- Lý do: Context expand cần lấy chunk liền trước/sau khi chunk quá ngắn

-- [6] B-Tree trên embed_status — Tìm chunks chưa embed
--     Query: SELECT * FROM chunks WHERE embed_status = 'pending'
CREATE INDEX idx_chunks_embed_status
    ON chunks (embed_status)
    WHERE embed_status != 'done';  -- Partial index: chỉ index pending + error
-- Lý do: Resume ingest sau khi gián đoạn — tìm chunks chưa được embed

-- [7] B-Tree trên created_at — Sort và filter theo thời gian
CREATE INDEX idx_chunks_created_at
    ON chunks (created_at DESC);
-- Lý do: Admin queries, pagination, lấy chunks mới nhất

-- [8] GIN trên keywords (JSONB array) — Tìm chunks có keyword cụ thể
--     Query: SELECT * FROM chunks WHERE keywords @> '["RAG"]'
CREATE INDEX idx_chunks_keywords_gin
    ON chunks USING GIN (keywords);
-- Lý do: JSONB array cần GIN để tìm kiếm phần tử bên trong
--        B-Tree không thể index bên trong array

-- [9] GIN trên entities (JSONB array of objects) — Tìm chunks nhắc đến entity
--     Query: SELECT * FROM chunks WHERE entities @> '[{"name": "OpenAI"}]'
CREATE INDEX idx_chunks_entities_gin
    ON chunks USING GIN (entities);
-- Lý do: GIN hỗ trợ containment operator @> trên JSONB object/array
--        Cần để tìm chunks liên quan đến 1 entity khi rerank

-- [10] GIN trên hypothetical_questions — Tìm questions có chứa keyword
--      Query: SELECT * FROM chunks WHERE hypothetical_questions @> '["chatbot"]'
CREATE INDEX idx_chunks_hypo_questions_gin
    ON chunks USING GIN (hypothetical_questions);
-- Lý do: Khi debug, cần kiểm tra hypothetical questions đã generate

-- [11] GIN Full-text search trên clean_text (tiếng Anh)
--      Query: SELECT * FROM chunks WHERE to_tsvector('english', clean_text) @@ plainto_tsquery('RAG system')
CREATE INDEX idx_chunks_clean_text_fts
    ON chunks USING GIN (to_tsvector('english', COALESCE(clean_text, '')));
-- Lý do: PostgreSQL FTS như mini-Elasticsearch (backup khi ES không có)
--        GIN index tsvector cho phép tìm nhanh mà không generate tsvector realtime
-- Lưu ý: Nếu dùng tiếng Việt → dùng 'simple' thay vì 'english'
--         CREATE INDEX ... ON chunks USING GIN (to_tsvector('simple', COALESCE(clean_text, '')))

-- [12] GIN Full-text search trên title + summary — Tìm theo tiêu đề
CREATE INDEX idx_chunks_title_summary_fts
    ON chunks USING GIN (
        to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(summary, ''))
    );
-- Lý do: Title và summary là text ngắn, thường dùng 'simple' để không bỏ từ

-- =============================================
-- INDEX cho bảng documents
-- =============================================

-- [13] B-Tree trên status — Filter documents đang processing
CREATE INDEX idx_documents_status
    ON documents (status)
    WHERE status != 'ready';  -- Partial index: chỉ index trạng thái chưa xong
-- Lý do: Kiểm tra documents nào đang ingest

-- [14] B-Tree trên created_at — Sort document mới nhất
CREATE INDEX idx_documents_created_at
    ON documents (created_at DESC);

-- =============================================
-- INDEX cho bảng search_logs
-- =============================================

-- [15] B-Tree trên created_at — Phân tích log theo thời gian
CREATE INDEX idx_search_logs_created_at
    ON search_logs (created_at DESC);
```

---

### 4.3 Cách kiểm tra Index có được dùng không

```sql
-- Xem query plan — nếu thấy "Index Scan" = index đang được dùng
-- Nếu thấy "Seq Scan" = index không được dùng hoặc chưa có
EXPLAIN ANALYZE
    SELECT chunk_id, title, summary
    FROM chunks
    WHERE doc_id = 'your-uuid-here'
      AND level = 2
    ORDER BY seq_no;

-- Output mong muốn:
-- Index Scan using idx_chunks_doc_level_seq on chunks
--   Index Cond: ((doc_id = '...') AND (level = 2))

-- Xem tất cả index trong database
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

-- Xem index nào đang được dùng nhiều nhất
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,          -- Số lần index được dùng
    idx_tup_read,      -- Số rows đọc qua index
    idx_tup_fetch      -- Số rows thực sự fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

---

### 4.4 Chiến lược Index theo từng Use Case

| Use Case | Query mẫu | Index dùng |
|---|---|---|
| Lấy tất cả chunks của 1 document | `WHERE doc_id = X AND level = 2 ORDER BY seq_no` | `idx_chunks_doc_level_seq` |
| Context expand: lấy parent | `WHERE chunk_id = parent_id` | Primary Key (tự động) |
| Context expand: lấy prev/next | `WHERE prev_id = X` hoặc `next_id = X` | `idx_chunks_prev_id`, `idx_chunks_next_id` |
| Resume ingest: tìm chunks pending | `WHERE embed_status = 'pending'` | `idx_chunks_embed_status` |
| Tìm chunks có keyword "RAG" | `WHERE keywords @> '["RAG"]'` | `idx_chunks_keywords_gin` |
| Backup FTS khi ES down | `WHERE tsvector @@ query` | `idx_chunks_clean_text_fts` |
| Xóa document + cascade | `DELETE FROM documents WHERE doc_id = X` | `idx_chunks_doc_id` (cho cascade) |

---

### 4.5 Lưu ý quan trọng về Index

```
1. KHÔNG index mọi cột — Index chiếm disk và làm chậm INSERT/UPDATE
   → Chỉ index những cột WHERE, JOIN, ORDER BY thường xuyên

2. Partial Index cực kỳ hiệu quả — Chỉ index rows thỏa mãn điều kiện
   → idx_chunks_embed_status chỉ index 'pending' + 'error', bỏ 'done'
   → Nhỏ hơn full index, nhanh hơn khi filter

3. GIN cho JSONB — KHÔNG dùng B-Tree cho JSONB array
   → B-Tree không thể tìm kiếm bên trong array/object
   → GIN hỗ trợ @>, ?, ?|, ?& operators

4. Composite Index — Thứ tự cột quan trọng
   → idx_chunks_doc_level_seq: (doc_id, level, seq_no)
   → Có thể dùng cho: WHERE doc_id = X (prefix match)
   → Có thể dùng cho: WHERE doc_id = X AND level = 2 (prefix match)
   → KHÔNG dùng được cho: WHERE level = 2 (không phải prefix)

5. CONCURRENTLY — Tạo index không lock bảng
   → CREATE INDEX CONCURRENTLY idx_name ON table (col);
   → Dùng trong production để tránh downtime
```

---

## 5. Schema lưu trong từng DB

### 5.1 Qdrant (Vector DB)
```python
# Mỗi Point trong Qdrant collection "chunks"
{
    "id": "chunk_id (UUID)",           # Khóa đồng bộ với PostgreSQL
    "vector": {
        "dense": [0.1, 0.2, ...],      # 1536 dims — OpenAI text-embedding-3-small
        "sparse": {"indices": [...], "values": [...]}  # BM25/SPLADE sparse vector
    },
    "payload": {
        "chunk_id": "...",
        "doc_id": "...",
        "level": 2,
        "title": "...",
        "summary": "...",
        "clean_text": "...",           # Để hiển thị kết quả
        "source_file": "input.txt",
        "seq_no": 12
    }
}
```

### 5.2 Elasticsearch (Keyword DB)
```json
// Index: "rag_chunks"
// Document ID = chunk_id
{
    "chunk_id": "uuid",
    "doc_id": "uuid",
    "clean_text": "Nội dung đầy đủ để full-text search",
    "title": "Tiêu đề LLM tạo",
    "summary": "Tóm tắt ngắn",
    "keywords": ["RAG", "LLM", "vector search"],
    "hypothetical_questions": [
        "Làm sao để AI không bịa thông tin?",
        "Chatbot công ty tôi hay sai, fix thế nào?",
        "Cách kết nối knowledge base với LLM?",
        "Grounding AI with real documents là gì?",
        "Kỹ thuật giúp AI trả lời dựa trên tài liệu thật?"
    ],
    "level": 2,
    "seq_no": 12
}
```

### 5.3 Neo4j (Graph DB)
```cypher
// Nodes
(:Chunk {chunk_id, title, summary, level, seq_no})
(:Entity {name, type})          // type: PERSON, ORG, CONCEPT, LOCATION
(:Document {doc_id, file_name})

// Relationships
(:Chunk)-[:BELONGS_TO]->(:Document)
(:Chunk)-[:PARENT_OF]->(:Chunk)       // Hierarchical
(:Chunk)-[:NEXT]->(:Chunk)            // Linked list
(:Chunk)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATES_TO {relation}]->(:Entity)
```

---

## 6. Pipeline INGEST — Trình tự bắt buộc

```
input.txt
    │
    ▼
[BƯỚC 1] PARSE & CLEAN
    - Đọc file text
    - Remove: số trang, header/footer lặp, ký tự đặc biệt
    - Normalize whitespace, encoding UTF-8
    - Tạo doc_id (UUID), insert vào PostgreSQL documents table (status='processing')
    │
    ▼
[BƯỚC 2] HIERARCHICAL SPLIT (cấp Section)
    - Tách theo Heading, dấu phân cách rõ ràng (===, ---, newline kép)
    - Tạo chunk Level 1 (Section) — ~800-1200 token mỗi section
    - Gán chunk_id (UUID) cho mỗi section NGAY LẬP TỨC
    - Insert vào PostgreSQL (level=1, embed_status='pending')
    │
    ▼
[BƯỚC 3] SEMANTIC CHUNKING (cấp Paragraph)
    - Với mỗi Section → tách thành các Paragraph
    - Phương pháp: embed từng câu → đo cosine distance
    - Nếu cosine distance > 0.4 → điểm cắt ngữ nghĩa
    - Target size: ~300-512 token mỗi paragraph
    - Overlap: 64 token với chunk kế tiếp
    - Gán chunk_id, set parent_id = section_id
    - Set prev_id/next_id để tạo linked list
    - Insert vào PostgreSQL (level=2, embed_status='pending')
    │
    ▼
[BƯỚC 4] LLM ENRICHMENT (gọi Claude cho mỗi chunk Level 2)
    Prompt → Claude trả về JSON:
    {
        "title": "Tên ngắn gọn của đoạn này",
        "summary": "Tóm tắt 2-3 câu",
        "keywords": ["từ khóa 1", "từ khóa 2", ...],  // max 10
        "entities": [
            {"name": "...", "type": "PERSON|ORG|CONCEPT|LOCATION"}
        ],
        "relations": [
            {"from": "Entity A", "relation": "RELATES_TO", "to": "Entity B"}
        ],
        "hypothetical_questions": [
            "Câu hỏi 1 người dùng thật hay hỏi",
            "Câu hỏi 2", "Câu hỏi 3", "Câu hỏi 4", "Câu hỏi 5"
        ]
    }
    - UPDATE PostgreSQL: title, summary, keywords, entities, hypothetical_questions, relations
    │
    ▼
[BƯỚC 5] EMBEDDING
    - Embed clean_text của mỗi Level 2 chunk
    - Model: text-embedding-3-small (OpenAI) — 1536 dims
    - UPDATE PostgreSQL: embed_status = 'done', embed_model = 'text-embedding-3-small'
    │
    ▼
[BƯỚC 6] WRITE SONG SONG vào 3 DB chuyên biệt
    ├── Qdrant: upsert point (chunk_id, dense_vector, sparse_vector, payload)
    ├── Elasticsearch: index document (chunk_id, clean_text, keywords, hypo_questions)
    └── Neo4j: create Chunk node + Entity nodes + relationships

[BƯỚC 7] FINALIZE
    - UPDATE PostgreSQL documents: status = 'ready', total_chunks = N
    - Log summary: số chunks, thời gian, số entities
```

---

## 7. Pipeline SEARCH — Trình tự khi user hỏi

```
User: "câu hỏi của người dùng"
    │
    ▼
[BƯỚC 1] QUERY REWRITE (Claude)
    - Claude viết lại câu hỏi thành 3 phiên bản:
      + Phiên bản gốc
      + Phiên bản kỹ thuật/formal hơn
      + Phiên bản ngắn gọn keyword-style
    │
    ▼
[BƯỚC 2] SEARCH SONG SONG 3 DB (top 3 mỗi DB = 9 kết quả)

    ├── Qdrant search (Vector DB)
    │   - Embed query → dense vector
    │   - Hybrid search: dense (0.7) + sparse BM25 (0.3)
    │   - Filter: level = 2 (chỉ lấy paragraph level)
    │   - Trả về: top 3 chunk_id + score
    │
    ├── Elasticsearch search (Keyword DB)
    │   - Multi-match query trên: clean_text + title + keywords + hypothetical_questions
    │   - boost hypothetical_questions x2 (vì match từ người dùng hay nhất)
    │   - Trả về: top 3 chunk_id + BM25 score
    │
    └── Neo4j search (Graph DB)
        - Extract entity từ câu hỏi
        - Tìm Chunk nodes MENTIONS entity đó
        - Expand: lấy thêm chunks liên kết qua RELATES_TO (1-2 hop)
        - Trả về: top 3 chunk_id + relevance score
    │
    ▼
[BƯỚC 3] RRF MERGE (Reciprocal Rank Fusion)
    - Gom 9 chunk_id (có thể trùng nhau)
    - Tính RRF score: score(chunk) = Σ 1/(60 + rank_i)
    - Chunk nào xuất hiện nhiều DB → điểm cao hơn
    - Deduplicate tự động vì dùng chung chunk_id
    - Kết quả: ranked list tối đa 9 chunk (thường 6-7 unique)
    │
    ▼
[BƯỚC 4] CONTEXT EXPAND (từ PostgreSQL Meta Table)
    - Với top 6 chunk sau RRF, query PostgreSQL:
      + Lấy parent (Section Level 1) qua parent_id
      + Lấy prev_id và next_id nếu chunk quá ngắn (< 200 token)
      + Query dùng: idx_chunks_parent_id, idx_chunks_prev_id, idx_chunks_next_id
    │
    ▼
[BƯỚC 5] RERANK
    - Từ 9 kết quả → chọn top 6 (2 từ mỗi DB sau RRF)
    - Nếu có Cohere Rerank API → dùng để rerank chính xác hơn
    - Nếu không → dùng RRF score làm final rank
    │
    ▼
[BƯỚC 6] LLM GENERATE (Claude)
    System prompt:
        "Bạn là AI trợ lý. Trả lời câu hỏi DỰA TRÊN tài liệu được cung cấp.
        Nếu tài liệu không có thông tin, nói rõ 'Tôi không tìm thấy thông tin này trong tài liệu'.
        Luôn cite nguồn (chunk_id hoặc tiêu đề đoạn)."

    User message:
        "Câu hỏi: [câu hỏi gốc]

        Tài liệu tham khảo:
        [Chunk 1 - title]: content...
        [Chunk 2 - title]: content...
        ...
        [Chunk 6 - title]: content..."
    │
    ▼
[BƯỚC 7] LOG
    - Insert vào PostgreSQL search_logs: query, chunks dùng, response, latency
    │
    ▼
Kết quả cuối: Câu trả lời + nguồn trích dẫn
```

---

## 8. Code mẫu: db/meta_db.py (PostgreSQL)

```python
# db/meta_db.py
import asyncpg
import json
from uuid import UUID
from config import PG_DSN

class MetaDB:
    """PostgreSQL client cho Meta Table"""

    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)

    async def close(self):
        await self.pool.close()

    # --------------------------------------------------
    # Documents
    # --------------------------------------------------
    async def create_document(self, file_name: str, file_path: str) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO documents (file_name, file_path, status)
                VALUES ($1, $2, 'processing')
                RETURNING doc_id::TEXT
                """,
                file_name, file_path
            )
            return row["doc_id"]

    async def finalize_document(self, doc_id: str, total_chunks: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET status = 'ready', total_chunks = $2, updated_at = NOW()
                WHERE doc_id = $1
                """,
                doc_id, total_chunks
            )

    # --------------------------------------------------
    # Chunks
    # --------------------------------------------------
    async def insert_chunk(self, chunk: dict) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO chunks (
                    doc_id, level, parent_id, prev_id, next_id, seq_no,
                    raw_text, clean_text, token_count, source_file, char_start, char_end
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING chunk_id::TEXT
                """,
                chunk["doc_id"], chunk["level"],
                chunk.get("parent_id"), chunk.get("prev_id"), chunk.get("next_id"),
                chunk["seq_no"], chunk["raw_text"], chunk["clean_text"],
                chunk.get("token_count"), chunk.get("source_file"),
                chunk.get("char_start"), chunk.get("char_end")
            )
            return row["chunk_id"]

    async def update_enrichment(self, chunk_id: str, enrichment: dict):
        """Cập nhật sau khi LLM enrichment xong"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET title = $2,
                    summary = $3,
                    keywords = $4::JSONB,
                    entities = $5::JSONB,
                    hypothetical_questions = $6::JSONB,
                    relations = $7::JSONB,
                    updated_at = NOW()
                WHERE chunk_id = $1
                """,
                chunk_id,
                enrichment["title"],
                enrichment["summary"],
                json.dumps(enrichment["keywords"]),
                json.dumps(enrichment["entities"]),
                json.dumps(enrichment["hypothetical_questions"]),
                json.dumps(enrichment["relations"])
            )

    async def mark_embedded(self, chunk_id: str, model: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET embed_status = 'done', embed_model = $2, updated_at = NOW()
                WHERE chunk_id = $1
                """,
                chunk_id, model
            )

    async def get_context(self, chunk_ids: list[str]) -> list[dict]:
        """Lấy chunk + parent + prev/next để expand context"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.*, p.clean_text AS parent_text, p.title AS parent_title
                FROM chunks c
                LEFT JOIN chunks p ON c.parent_id = p.chunk_id
                WHERE c.chunk_id = ANY($1::UUID[])
                ORDER BY c.seq_no
                """,
                chunk_ids
            )
            return [dict(r) for r in rows]

    async def get_pending_embed(self, limit: int = 50) -> list[dict]:
        """Lấy chunks chưa embed — dùng idx_chunks_embed_status"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id::TEXT, clean_text, doc_id::TEXT
                FROM chunks
                WHERE embed_status = 'pending' AND level = 2
                ORDER BY created_at
                LIMIT $1
                """,
                limit
            )
            return [dict(r) for r in rows]
```

---

## 9. Cấu hình hệ thống (config.py)

```python
# config.py
import os

# LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LLM_MODEL         = "claude-sonnet-4-20250514"
EMBED_MODEL       = "text-embedding-3-small"  # OpenAI

# Chunking
CHUNK_SIZE_SECTION   = 1000   # token — Level 1
CHUNK_SIZE_PARAGRAPH = 512    # token — Level 2
CHUNK_OVERLAP        = 64     # token overlap
SEMANTIC_THRESHOLD   = 0.4    # cosine distance để cắt

# Hypothetical Questions
NUM_HYPO_QUESTIONS = 5

# PostgreSQL (thay SQLite)
PG_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db"
)

# Qdrant
QDRANT_URL        = "http://localhost:6333"
QDRANT_COLLECTION = "rag_chunks"
VECTOR_DIM        = 1536

# Elasticsearch
ES_URL   = "http://localhost:9200"
ES_INDEX = "rag_chunks"

# Neo4j
NEO4J_URL      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "password"

# Search
SEARCH_TOP_K    = 3    # Mỗi DB trả về top 3
FINAL_TOP_K     = 6    # Sau RRF chọn top 6
RRF_K           = 60   # Hằng số RRF chuẩn

# Hybrid search weights (Qdrant)
DENSE_WEIGHT  = 0.7
SPARSE_WEIGHT = 0.3
```

---

## 10. docker-compose.yml

```yaml
version: '3.8'
services:

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: rag_db
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: rag_password
    ports:
      - "5432:5432"
    volumes:
      - pg_storage:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d   # Tự chạy migration khi khởi động
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rag_user -d rag_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage

  elasticsearch:
    image: elasticsearch:8.13.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - es_storage:/usr/share/elasticsearch/data

  neo4j:
    image: neo4j:5.18-community
    environment:
      - NEO4J_AUTH=neo4j/password
    ports:
      - "7474:7474"   # Browser UI
      - "7687:7687"   # Bolt
    volumes:
      - neo4j_storage:/data

volumes:
  pg_storage:
  qdrant_storage:
  es_storage:
  neo4j_storage:
```

---

## 11. requirements.txt

```
# LLM
anthropic>=0.25.0
openai>=1.0.0

# Vector DB
qdrant-client>=1.9.0

# Keyword DB
elasticsearch>=8.13.0

# Graph DB
neo4j>=5.18.0

# PostgreSQL (thay SQLite)
asyncpg>=0.29.0          # Async PostgreSQL driver
psycopg2-binary>=2.9.9   # Sync driver (backup, migrations)

# Embedding & NLP
sentence-transformers>=3.0.0
nltk>=3.8.0
tiktoken>=0.7.0

# Core
numpy>=1.26.0
pydantic>=2.0.0
python-dotenv>=1.0.0

# API (optional)
fastapi>=0.111.0
uvicorn>=0.29.0
```

---

## 12. Kế hoạch thực hiện — Phase by Phase

### Phase 1: Setup môi trường (1-2 ngày)
- [ ] Clone repo, tạo cấu trúc thư mục
- [ ] Cài requirements.txt
- [ ] Chạy `docker-compose up -d` — khởi động PostgreSQL + 3 DB
- [ ] Test kết nối từng DB:
  - PostgreSQL: `psql -h localhost -U rag_user -d rag_db`
  - Qdrant: `curl http://localhost:6333/healthz`
  - Elasticsearch: `curl http://localhost:9200`
  - Neo4j: mở browser `http://localhost:7474`
- [ ] Tạo `.env` file với API keys và PG_DSN
- [ ] Chạy migration files để tạo tables + indexes trong PostgreSQL

### Phase 2: Pipeline Ingest (3-4 ngày)
- [ ] `chunker.py` — Hierarchical split theo heading/newline
- [ ] `chunker.py` — Semantic chunking (embed câu → cosine distance → cắt)
- [ ] `enricher.py` — Gọi Claude: title + summary + keywords + entities + hypothetical_questions
- [ ] `embedder.py` — Tạo dense vector (OpenAI text-embedding-3-small)
- [ ] `db/meta_db.py` — PostgreSQL client: insert/update chunks + documents
- [ ] `db/vector_db.py` — Write vào Qdrant
- [ ] `db/keyword_db.py` — Write vào Elasticsearch
- [ ] `db/graph_db.py` — Write nodes + edges vào Neo4j
- [ ] `ingestor.py` — Orchestrate toàn bộ pipeline
- [ ] Test: copy file text → chạy ingest → kiểm tra PostgreSQL + 3 DB có data
- [ ] Verify indexes: `EXPLAIN ANALYZE` các query chính

### Phase 3: Pipeline Search (2-3 ngày)
- [ ] `retriever.py` — Query rewrite (Claude)
- [ ] `retriever.py` — Search Qdrant (hybrid dense+sparse), lấy top 3
- [ ] `retriever.py` — Search Elasticsearch (multi-match + hypo Q boost), lấy top 3
- [ ] `retriever.py` — Search Neo4j (entity extraction + graph traversal), lấy top 3
- [ ] `retriever.py` — RRF merge 9 kết quả → top 6
- [ ] `retriever.py` — Context expand (lấy parent + prev/next từ PostgreSQL)
- [ ] `llm/client.py` — Gọi Claude với top 6 chunk → generate câu trả lời
- [ ] Log kết quả vào PostgreSQL search_logs

### Phase 4: Demo Interface (1-2 ngày)
- [ ] `main.py` — CLI đơn giản: nhập câu hỏi → in kết quả
- [ ] In rõ: chunk nào từ DB nào → score RRF → câu trả lời cuối
- [ ] (Optional) `api/main.py` — FastAPI endpoint POST /query

### Phase 5: Test & Tinh chỉnh (1-2 ngày)
- [ ] Test với 3-5 câu hỏi khác nhau
- [ ] Chạy `EXPLAIN ANALYZE` để confirm indexes đang được dùng
- [ ] Kiểm tra: 3 DB đều trả đúng top 3
- [ ] Kiểm tra: RRF merge đúng → top 6
- [ ] Điều chỉnh: CHUNK_SIZE, OVERLAP, SEMANTIC_THRESHOLD
- [ ] Điều chỉnh: dense/sparse weight trong Qdrant

---

## 13. Luồng dữ liệu tóm tắt

```
INPUT.TXT
    │
    ▼ chunker.py (Hierarchical + Semantic)
CHUNKS (Level 1: Section, Level 2: Paragraph)
    │
    ▼ enricher.py (Claude API)
ENRICHED CHUNKS (+ title, summary, keywords, entities, hypo_questions)
    │
    ▼ embedder.py
CHUNKS + VECTORS
    │
    ├──▶ PostgreSQL (Meta Table: chunk_id, parent, prev, next, JSONB enrichment)
    │       └── Indexes: B-Tree, GIN (JSONB), GIN (FTS)
    ├──▶ Qdrant (chunk_id, dense_vector, sparse_vector, payload)
    ├──▶ Elasticsearch (chunk_id, clean_text, keywords, hypo_questions)
    └──▶ Neo4j (Chunk nodes, Entity nodes, relationships)

USER QUERY
    │
    ▼ Query rewrite (Claude)
3 QUERY VARIANTS
    │
    ├──▶ Qdrant search → top 3 chunk_id + score
    ├──▶ Elasticsearch search → top 3 chunk_id + score
    └──▶ Neo4j search → top 3 chunk_id + score
                │
                ▼ RRF merge (9 → 6 unique)
        TOP 6 CHUNK_IDs
                │
                ▼ Context expand (PostgreSQL: parent + prev/next qua index)
        6 CHUNKS (đầy đủ context)
                │
                ▼ Claude generate
        CÂU TRẢ LỜI + NGUỒN TRÍCH DẪN
                │
                ▼ Log vào PostgreSQL search_logs
```

---

## 14. Ghi chú quan trọng

1. **chunk_id phải được gán TRƯỚC khi làm bất cứ gì** — UUID gán ngay lúc parse, không gán sau enrichment
2. **hypothetical_questions lưu Elasticsearch KHÔNG embed** — chỉ dùng BM25 text match
3. **Level 1 (Section) chỉ lưu PostgreSQL + Neo4j** — KHÔNG embed vào Qdrant (tránh noise)
4. **Level 2 (Paragraph) mới embed vào Qdrant** — đây là unit tìm kiếm chính
5. **Khi search chỉ tìm Level 2** — sau đó mới expand lên Level 1 để lấy context
6. **RRF k=60 là giá trị chuẩn** — không cần thay đổi trừ khi benchmark thấy cần
7. **Elasticsearch boost hypothetical_questions x2** — đây là lợi thế lớn nhất
8. **PostgreSQL thay SQLite** — dùng asyncpg (async), JSONB cho keywords/entities/hypo_questions, indexes phong phú hơn
9. **Chạy EXPLAIN ANALYZE sau khi tạo indexes** — confirm PostgreSQL dùng đúng index
10. **Migrations tự động qua Docker** — đặt SQL files trong `./migrations/` để PostgreSQL container tự chạy khi khởi động
