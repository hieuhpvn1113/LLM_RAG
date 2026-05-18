### ✅ Phase 2: Pipeline Ingest — HOÀN THÀNH
- [x] `core/chunker.py` — Hierarchical split (Level 1) + Semantic split (Level 2)
- [x] `core/enricher.py` — Groq LLM: title, summary, keywords, entities, hypo_questions
- [x] `core/embedder.py` — all-MiniLM-L6-v2, 384 dims, local
- [x] `db/meta_db.py` — PostgreSQL: insert/update chunks, linked list, enrichment
- [x] `db/vector_db.py` — Qdrant: upsert_batch + search
- [x] `db/keyword_db.py` — Elasticsearch: bulk index + BM25 search (hypo_questions x2)
- [x] `db/graph_db.py` — Neo4j: nodes + relationships + entity search
- [x] `core/ingestor.py` — Full pipeline: 7 chunks, 21s, 4/4 DB ✅
- [x] Test end-to-end: `data/input.txt` → 3 sections → 7 paragraphs → 4 DB

---

### 🚧 Phase 3: Pipeline Search — TIẾP THEO
- [ ] `core/retriever.py` — Query rewrite (Groq) → 3 phiên bản
- [ ] `core/retriever.py` — Search Qdrant hybrid, lấy top 3
- [ ] `core/retriever.py` — Search Elasticsearch multi-match + hypo Q boost, lấy top 3
- [ ] `core/retriever.py` — Search Neo4j entity + graph traversal, lấy top 3
- [ ] `core/retriever.py` — RRF merge 9 → top 6
- [ ] `core/retriever.py` — Context expand (PostgreSQL: parent + prev/next)
- [ ] `llm/client.py` — Generate answer (Groq) với top 6 chunks
- [ ] Log kết quả vào PostgreSQL search_logs
- [ ] `main.py` — CLI query command hoạt động

### Phase 4: Demo Interface (1-2 ngày)
- [ ] `main.py` — CLI: nhập câu hỏi → in kết quả có nguồn trích dẫn
- [ ] In rõ: chunk nào từ DB nào → score RRF → câu trả lời cuối
- [ ] (Optional) `api/main.py` — FastAPI endpoint POST /query

### Phase 5: Test & Tinh chỉnh (1-2 ngày)
- [ ] Test với 3-5 câu hỏi khác nhau
- [ ] Chạy `EXPLAIN ANALYZE` để confirm indexes đang được dùng
- [ ] Kiểm tra 3 DB đều trả đúng top 3
- [ ] Điều chỉnh: CHUNK_SIZE, OVERLAP, SEMANTIC_THRESHOLD
- [ ] Điều chỉnh: dense/sparse weight trong Qdrant
