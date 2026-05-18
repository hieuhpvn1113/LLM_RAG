# core/ingestor.py — Orchestrate toàn bộ pipeline ingest
"""
Pipeline đầy đủ:
  1.  Đọc + clean file text
  2.  Insert Document vào PostgreSQL (status='processing')
  3.  Hierarchical Split → Level 1 Sections
  4.  Insert Level 1 chunks vào PostgreSQL + Neo4j
  5.  Semantic Split mỗi Section → Level 2 Paragraphs
  6.  Insert Level 2 chunks vào PostgreSQL (KHÔNG có prev/next_id trước)
  7.  Update prev_id / next_id sau khi tất cả đã insert (tránh FK violation)
  8.  LLM Enrichment (Groq) — title, summary, keywords, entities, hypo_questions
  9.  Update enrichment vào PostgreSQL
  10. Embed Level 2 chunks (all-MiniLM-L6-v2, batch)
  11. Write vào Qdrant (dense vector + payload)
  12. Write vào Elasticsearch (text + keywords + hypo_questions)
  13. Write vào Neo4j (Chunk nodes + Entity nodes + relationships)
  14. Finalize — documents.status = 'ready'
"""

import asyncio
import time
from pathlib import Path

from core.chunker  import hierarchical_split, semantic_split, clean_text
from core.enricher import enrich_chunk
from core.embedder import embed_batch
from db.meta_db    import MetaDB
from db.vector_db  import VectorDB
from db.keyword_db import KeywordDB
from db.graph_db   import GraphDB
from llm.client    import AsyncLLMClient
from config        import EMBED_MODEL


async def ingest_file(file_path: str) -> str:
    """
    Ingest 1 file text vào toàn bộ hệ thống RAG.
    Returns: doc_id (UUID string)
    """
    start_time = time.time()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File không tồn tại: {file_path}")

    print(f"\n{'='*60}")
    print(f"  📄 Ingest: {path.name}")
    print(f"{'='*60}")

    meta_db   = MetaDB()
    vector_db = VectorDB()
    kw_db     = KeywordDB()
    graph_db  = GraphDB()
    llm       = AsyncLLMClient()

    await meta_db.connect()
    vector_db.connect();   vector_db.ensure_collection()
    kw_db.connect();       kw_db.ensure_index()
    graph_db.connect();    graph_db.ensure_constraints()

    try:
        # ── BƯỚC 1: Đọc file ─────────────────────────────────────────────────
        print("\n[1/7] Đọc file...")
        raw_text  = path.read_text(encoding='utf-8', errors='replace')
        text      = clean_text(raw_text)
        print(f"  File size : {path.stat().st_size:,} bytes")
        print(f"  Text len  : {len(text):,} chars")

        # ── BƯỚC 2: Document record ──────────────────────────────────────────
        print("\n[2/7] Tạo document record...")
        doc_id = await meta_db.create_document(path.name, str(path.resolve()))
        graph_db.upsert_document(doc_id, path.name)
        print(f"  doc_id: {doc_id}")

        # ── BƯỚC 3: Hierarchical Split → Level 1 ─────────────────────────────
        print("\n[3/7] Hierarchical split (Level 1 — Sections)...")
        l1_chunks = hierarchical_split(text, doc_id, path.name)
        print(f"  → {len(l1_chunks)} sections")
        for chunk in l1_chunks:
            await meta_db.insert_chunk(chunk)
            graph_db.upsert_chunk_node(chunk)

        # ── BƯỚC 4: Semantic Split → Level 2 ─────────────────────────────────
        print("\n[4/7] Semantic split (Level 2 — Paragraphs)...")
        all_l2_chunks = []
        for i, section in enumerate(l1_chunks, 1):
            l2 = semantic_split(section, doc_id)
            print(f"  Section {i:2d}/{len(l1_chunks)}: "
                  f"{section['token_count']:4d} tokens → {len(l2)} paragraphs")
            all_l2_chunks.extend(l2)
        print(f"  → Tổng: {len(all_l2_chunks)} paragraphs (Level 2)")

        # Insert Level 2 — QUAN TRỌNG: bỏ prev_id/next_id lúc insert
        # để tránh ForeignKeyViolationError (chunk chưa tồn tại trong DB)
        for chunk in all_l2_chunks:
            chunk_to_insert = {**chunk, 'prev_id': None, 'next_id': None}
            await meta_db.insert_chunk(chunk_to_insert)

        # Sau khi TẤT CẢ chunks đã có trong DB → update linked list
        print(f"  Cập nhật linked list (prev/next)...")
        for chunk in all_l2_chunks:
            if chunk.get('prev_id') or chunk.get('next_id'):
                await meta_db.update_chunk_links(
                    chunk['chunk_id'],
                    chunk.get('prev_id'),
                    chunk.get('next_id'),
                )

        # ── BƯỚC 5: LLM Enrichment ───────────────────────────────────────────
        print(f"\n[5/7] LLM Enrichment ({len(all_l2_chunks)} chunks via Groq)...")
        enriched_chunks = []
        for i, chunk in enumerate(all_l2_chunks, 1):
            print(f"  [{i:2d}/{len(all_l2_chunks)}] {chunk['token_count']:4d} tok...",
                  end='', flush=True)

            enrichment = await enrich_chunk(chunk['clean_text'], llm)
            chunk.update({
                'title':                  enrichment['title'],
                'summary':                enrichment['summary'],
                'keywords':               enrichment['keywords'],
                'entities':               enrichment['entities'],
                'relations':              enrichment['relations'],
                'hypothetical_questions': enrichment['hypothetical_questions'],
            })
            enriched_chunks.append(chunk)
            await meta_db.update_enrichment(chunk['chunk_id'], enrichment)

            title_preview = enrichment['title'][:45] or '(no title)'
            print(f" ✓  \"{title_preview}\"")

            # Groq free tier: ~30 req/min → delay nhỏ giữa các request
            if i % 25 == 0:
                print("  ⏳ Đợi 12s (rate limit buffer)...")
                await asyncio.sleep(12)
            else:
                await asyncio.sleep(0.5)

        # ── BƯỚC 6: Embedding ────────────────────────────────────────────────
        print(f"\n[6/7] Embedding {len(enriched_chunks)} chunks ({EMBED_MODEL})...")
        vectors = embed_batch([c['clean_text'] for c in enriched_chunks])
        print(f"  → {len(vectors)} vectors, dim={len(vectors[0])}")
        for chunk in enriched_chunks:
            await meta_db.mark_embedded(chunk['chunk_id'], EMBED_MODEL)

        # ── BƯỚC 7: Write vào 3 DB ───────────────────────────────────────────
        print(f"\n[7/7] Write → Qdrant + Elasticsearch + Neo4j...")

        vector_db.upsert_batch(enriched_chunks, vectors)
        kw_db.index_batch(enriched_chunks)

        print(f"  Neo4j: {len(enriched_chunks)} chunks + entities...")
        for chunk in enriched_chunks:
            graph_db.write_chunk_full(chunk)
        print(f"  Neo4j: ✓")

        # ── Finalize ─────────────────────────────────────────────────────────
        await meta_db.finalize_document(doc_id, len(enriched_chunks))

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"  ✅ Ingest hoàn thành!")
        print(f"  doc_id     : {doc_id}")
        print(f"  Sections   : {len(l1_chunks)}")
        print(f"  Paragraphs : {len(enriched_chunks)}")
        print(f"  Thời gian  : {elapsed:.1f}s")
        print(f"{'='*60}\n")
        return doc_id

    finally:
        await meta_db.close()
        graph_db.close()


async def ingest_directory(dir_path: str) -> list:
    """Ingest tất cả .txt trong 1 thư mục."""
    txt_files = list(Path(dir_path).glob('*.txt'))
    if not txt_files:
        print(f"Không tìm thấy file .txt trong {dir_path}")
        return []
    doc_ids = []
    for fp in txt_files:
        try:
            doc_ids.append(await ingest_file(str(fp)))
        except Exception as e:
            print(f"  ❌ Lỗi {fp.name}: {e}")
    return doc_ids


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m core.ingestor <file.txt>")
        sys.exit(1)
    asyncio.run(ingest_file(sys.argv[1]))
