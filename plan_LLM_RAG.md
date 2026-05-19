# Plan: He thong RAG thong minh - Vector + Keyword + Graph DB

> Muc tieu: Xay dung demo he thong RAG truy xuat chinh xac tren du lieu noi bo.
> 
> Input: File text do nguoi dung cung cap.
> 
> Output: Cau tra loi tu LLM co trich dan nguon ro rang.
> 
> Cap nhat: 2026-05 | Trang thai: Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4 ✅ · Phase 5 🚧

---

## 1) Kien truc du an hien tai

- PostgreSQL (`meta DB`): luu metadata tai lieu/chunk va search logs.
  - Bang: `documents`, `chunks`, `search_logs`.
  - Metadata chunk gom: `title`, `summary`, `keywords`, `entities`, `hypothetical_questions`, `relations`, `prev_id/next_id`, `parent_id`, `token_count`, `embed_status`, `embed_model`.
- Qdrant (`vector DB`): luu vector embedding Level 2 va tim kiem dense.
- Elasticsearch (`keyword DB`): index BM25 cho text, title, keywords, hypothetical questions.
- Neo4j (`graph DB`): luu entity va quan he de search theo do thi.
- Groq LLM:
  - Enrichment luc ingest.
  - Query rewrite + answer generation luc retrieval.

Ket luan: **Meta da duoc luu o PostgreSQL** thong qua `db/meta_db.py` (`create_document`, `insert_chunk`, `update_enrichment`, `mark_embedded`, `log_search`).

---

## 2) Mapping code theo module

- `core/chunker.py`: tach chunk Level 1/Level 2.
- `core/enricher.py`: tao title/summary/keywords/entities/hypo questions.
- `core/embedder.py`: tao embedding local (`all-MiniLM-L6-v2`, 384 dims).
- `core/ingestor.py`: pipeline ingest va ghi vao 4 DB.
- `core/retriever.py`: rewrite -> search 3 DB -> RRF -> context expand -> answer -> log.
- `db/meta_db.py`: thao tac PostgreSQL metadata.
- `db/vector_db.py`: thao tac Qdrant.
- `db/keyword_db.py`: thao tac Elasticsearch.
- `db/graph_db.py`: thao tac Neo4j.
- `main.py`: CLI (`ingest`, `query`).
- `api/main.py`: placeholder (chua implement API).

---

## 3) Tien do phase

### Phase 1 - Setup moi truong (Done)
- [x] Docker compose cho PostgreSQL, Qdrant, Elasticsearch, Neo4j.
- [x] Tao `.env`, ket noi 4/4 services.
- [x] Chay migration tao schema va indexes.

### Phase 2 - Pipeline ingest (Done)
- [x] Chunking 2 level + semantic split.
- [x] LLM enrichment metadata.
- [x] Embed Level 2 va upsert Qdrant.
- [x] Index Elasticsearch.
- [x] Upsert entity/relations vao Neo4j.
- [x] Luu metadata va link prev/next vao PostgreSQL.

### Phase 3 - Pipeline search (Done)
- [x] Query rewrite (3 variants).
- [x] Search Qdrant + Elasticsearch + Neo4j (top-k moi nguon).
- [x] RRF merge ket qua.
- [x] Context expand tu PostgreSQL (parent + prev/next khi can).
- [x] Generate answer co trich dan.
- [x] Ghi `search_logs` vao PostgreSQL.

### Phase 4 - Demo interface (Done)
- [x] CLI `python main.py ingest <file>`.
- [x] CLI `python main.py query "..."`.
- [x] Verbose output cho rewrite/search/RRF/source.
- [x] FastAPI (`api/main.py`) - da implement endpoint `/health`, `/query`, `/ingest`.

### Phase 5 - Test va tinh chinh (In progress)
- [ ] Test voi >= 5 cau hoi da dang: factual, conceptual, entity-based, technical.
- [ ] Chay `EXPLAIN ANALYZE` de xac nhan index usage tren PostgreSQL.
- [ ] Verify graph trong Neo4j Browser (`http://localhost:7474`).
- [ ] Ingest tai lieu dai (>50 chunks) de test scale.
- [ ] Dieu chinh `SEMANTIC_THRESHOLD`, `CHUNK_SIZE_PARAGRAPH`, `CHUNK_OVERLAP` neu can.
- [ ] Tinh chinh prompt query rewrite cho technical variant.
- [ ] (Optional) Implement `api/main.py` voi endpoint `POST /query`.

---

## 4) Luu y van hanh

- PostgreSQL host port dang dung: `5433` (container la `5432`).
- FK an toan khi ingest: insert chunk truoc voi `prev_id/next_id = NULL`, update links sau.
- Qdrant client moi: uu tien `query_points()` thay vi API cu.
- Elasticsearch can version/header tuong thich voi server v8.
- Neo4j query params: tranh dat ten param la `query` de khong trung keyword.
- Rate limit Groq free tier: can retry/backoff khi ingest tai lieu lon.

---

## 5) Definition of done cho Phase 5

- 5/5 (hoac hon) test query tra loi dung y va co trich dan hop ly.
- `EXPLAIN ANALYZE` cho thay indexes chinh duoc su dung o truy van context/log.
- Neo4j co nodes/relationships dung nhu entity extraction.
- Ingest tai lieu dai thanh cong, retrieval van on dinh, latency chap nhan duoc.
- Co ghi nhan tuning cu the (tham so truoc/sau va tac dong).
