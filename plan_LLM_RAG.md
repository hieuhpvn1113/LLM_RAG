# 🧠 Plan: Hệ thống RAG thông minh — Vector + Keyword + Graph DB

> **Mục tiêu:** Demo/Test hệ thống lưu trữ và tìm kiếm dữ liệu thông minh bằng AI
> **Input:** File text do người dùng cung cấp
> **Output:** Câu trả lời chính xác từ LLM dựa trên dữ liệu thật
> **Cập nhật:** 2026-05 | **Trạng thái:** Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 🚧

---

## 8. Kế hoạch thực hiện — Phase by Phase

### ✅ Phase 1: Setup môi trường — HOÀN THÀNH
- [x] Clone repo, tạo cấu trúc thư mục
- [x] Cài requirements.txt + pip install groq
- [x] Chạy `docker-compose up -d` — 4 services chạy ổn định
  - [x] PostgreSQL 16.14 — port **5433** (đổi để tránh conflict với local PG)
  - [x] Qdrant — http://localhost:6333
  - [x] Elasticsearch v8.13.0 — http://localhost:9200
  - [x] Neo4j — bolt://localhost:7687
- [x] Tạo `.env` với GROQ_API_KEY + DATABASE_URL (port 5433)
- [x] Migration tự động qua Docker → 3 tables + 19 indexes ✅
  - [x] Table `documents`, `chunks`, `search_logs`
- [x] `test_connections.py` → **4/4 services ✅**

---

### ✅ Phase 2: Pipeline Ingest — HOÀN THÀNH
- [x] `core/chunker.py` — Hierarchical split (Level 1) + Semantic split cosine distance (Level 2)
- [x] `core/enricher.py` — Groq LLM: title, summary, keywords, entities, hypo_questions (retry + fallback)
- [x] `core/embedder.py` — all-MiniLM-L6-v2, 384 dims, local, batch embed
- [x] `db/meta_db.py` — PostgreSQL: insert/update chunks, linked list, enrichment, log
- [x] `db/vector_db.py` — Qdrant: upsert_batch + search (compat client v1/v2)
- [x] `db/keyword_db.py` — ES: bulk index + BM25 search hypo_questions boost x2
- [x] `db/graph_db.py` — Neo4j: nodes + relationships + entity search
- [x] `core/ingestor.py` — Full pipeline: FK-safe insert (prev/next sau khi insert xong)
- [x] `llm/client.py` — Sync + **AsyncGroq** client
- [x] Test end-to-end: `data/input.txt` → 3 sections → 7 paragraphs → **4 DB ✅** (21s)

**Bugs đã fix:**
- `ForeignKeyViolationError` next_id → insert NULL trước, update links sau
- `elasticsearch BadRequestError 400` client v9 vs server v8 → override headers
- `QdrantClient has no attribute 'search'` → dùng `query_points()` (API mới)

---

### ✅ Phase 3: Pipeline Search — HOÀN THÀNH
- [x] `core/retriever.py` — Query rewrite (Groq) → 3 phiên bản
- [x] `core/retriever.py` — Search Qdrant (dense vector, top 3)
- [x] `core/retriever.py` — Search Elasticsearch (multi-match + hypo boost x2, top 3)
- [x] `core/retriever.py` — Search Neo4j (entity extraction + graph traversal, top 3)
- [x] `core/retriever.py` — RRF merge 9 → top 5-6 unique
- [x] `core/retriever.py` — Context expand (PostgreSQL: parent + prev/next)
- [x] Generate answer (Groq) với nguồn trích dẫn rõ ràng
- [x] Log vào PostgreSQL search_logs

**Kết quả test:**
```
Query: "RAG là gì và tại sao nó quan trọng?"
  Qdrant    : 3 results (score 0.65, 0.60, 0.52)
  ES        : 3 results (score 14.07, 7.32, 6.64)
  Neo4j     : 3 results (score 1.0 x3)
  RRF top 1 : 'RAG System Retrieval' [qdrant+elasticsearch+neo4j] rrf=0.049
  Latency   : 8.8s (bao gồm Groq API call)
```

**Bugs đã fix:**
- `Session.run() multiple values for 'query'` → đổi param thành `user_query`

---

### ✅ Phase 4: Demo Interface — HOÀN THÀNH
- [x] `main.py` — CLI: `python main.py ingest <file>` + `python main.py query "câu hỏi"`
- [x] Verbose output: query rewrite → search scores → RRF rank → sources → answer
- [x] Nguồn trích dẫn rõ ràng: `[qdrant+elasticsearch+neo4j]` cho mỗi chunk

---

### 🚧 Phase 5: Test & Tinh chỉnh
- [ ] Test với 5+ câu hỏi đa dạng (factual, conceptual, entity-based)
- [ ] Chạy `EXPLAIN ANALYZE` để confirm indexes đang được dùng
- [ ] Kiểm tra Neo4j graph browser (http://localhost:7474) — xem nodes/relationships
- [ ] Thêm file tài liệu dài hơn (>50 chunks) để test scale
- [ ] Điều chỉnh `SEMANTIC_THRESHOLD` nếu chunks quá lớn/nhỏ
- [ ] Cải thiện query rewrite prompt để technical variant chính xác hơn
- [ ] (Optional) `api/main.py` — FastAPI endpoint POST /query

---

## 9. Ghi chú quan trọng

1. **Port PostgreSQL = 5433** (host) — tránh conflict với PostgreSQL cài local trên máy
2. **FK insert order** — insert chunks với prev/next=NULL, update links SAU KHI tất cả đã insert
3. **Qdrant API** — dùng `query_points()` không phải `search()` (client ≥ 1.7)
4. **ES headers** — cần override Accept/Content-Type khi client v8 kết nối server v8
5. **Neo4j param** — không đặt tên param là `query` (trùng với driver keyword) → dùng `user_query`
6. **Groq rate limit** — free tier ~30 req/min → delay 0.5s/request, 12s mỗi 25 requests
7. **Embedding** — all-MiniLM-L6-v2, 384 dims, local, không cần API key, lazy load
8. **RRF k=60** — chuẩn, chunk xuất hiện cả 3 DB sẽ nổi bật hơn hẳn
9. **Hypothetical questions** — quan trọng nhất trong ES search, boost x2
10. **Level 1** chỉ lưu PG + Neo4j, **Level 2** mới embed vào Qdrant
