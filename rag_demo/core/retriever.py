# core/retriever.py — Search Pipeline
"""
Pipeline search đầy đủ:
  1. Query Rewrite  — Groq viết lại thành 3 phiên bản
  2. Parallel Search — Qdrant + Elasticsearch + Neo4j (top 3 mỗi DB = 9 results)
  3. RRF Merge      — Gộp 9 → top 6 unique bằng Reciprocal Rank Fusion
  4. Context Expand — Lấy parent + prev/next từ PostgreSQL
  5. Generate       — Groq sinh câu trả lời có trích dẫn
  6. Log            — Ghi search_logs vào PostgreSQL
"""

import asyncio
import json
import re
import time

from db.meta_db    import MetaDB
from db.vector_db  import VectorDB
from db.keyword_db import KeywordDB
from db.graph_db   import GraphDB
from core.embedder import embed_text
from llm.client    import AsyncLLMClient
from llm.prompts   import (QUERY_REWRITE_SYSTEM, QUERY_REWRITE_USER,
                            ANSWER_SYSTEM, ANSWER_USER)
from config        import SEARCH_TOP_K, FINAL_TOP_K, RRF_K


# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 1: Query Rewrite
# ─────────────────────────────────────────────────────────────────────────────
async def rewrite_query(query: str, llm: AsyncLLMClient) -> dict:
    """
    Viết lại câu hỏi thành 3 phiên bản để tăng recall.

    Returns:
        {
          "original" : câu gốc,
          "technical": phiên bản kỹ thuật/formal,
          "keywords" : phiên bản ngắn gọn dạng keyword
        }
    """
    try:
        raw = await llm.complete(
            system=QUERY_REWRITE_SYSTEM,
            user=QUERY_REWRITE_USER.format(query=query),
            max_tokens=300,
        )
        # Strip markdown fences nếu có
        raw = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r'\s*```$', '', raw.strip())
        data = json.loads(raw)
        return {
            "original":  data.get("original",  query),
            "technical": data.get("technical", query),
            "keywords":  data.get("keywords",  query),
        }
    except Exception:
        # Fallback: dùng query gốc cho cả 3
        return {"original": query, "technical": query, "keywords": query}


# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 2: Parallel Search
# ─────────────────────────────────────────────────────────────────────────────
def search_qdrant(vector_db: VectorDB, query_text: str, top_k: int) -> list:
    """Dense vector search trên Qdrant."""
    qv = embed_text(query_text)
    return vector_db.search(qv, top_k=top_k)


def search_es(kw_db: KeywordDB, query_text: str, top_k: int) -> list:
    """BM25 multi-field search trên Elasticsearch."""
    return kw_db.search(query_text, top_k=top_k)


def search_neo4j(graph_db: GraphDB, query_text: str, top_k: int) -> list:
    """Entity-based graph search trên Neo4j."""
    entities = graph_db.extract_entities_simple(query_text)
    if not entities:
        return []
    return graph_db.search(entities, top_k=top_k)


# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 3: RRF Merge
# ─────────────────────────────────────────────────────────────────────────────
def rrf_merge(results_per_db: list, k: int = RRF_K, top_n: int = FINAL_TOP_K) -> list:
    """
    Reciprocal Rank Fusion — gộp kết quả từ nhiều DB.

    Args:
        results_per_db : list of list[dict], mỗi list là kết quả từ 1 DB
                         (đã sắp xếp theo score giảm dần)
        k              : hằng số RRF (mặc định 60)
        top_n          : số kết quả trả về sau merge

    Returns:
        list[dict] sắp xếp theo RRF score giảm dần
        Mỗi dict: {chunk_id, rrf_score, title, clean_text, sources}
    """
    scores: dict[str, float] = {}
    meta:   dict[str, dict]  = {}

    for db_results in results_per_db:
        for rank, item in enumerate(db_results, start=1):
            cid = item["chunk_id"]
            rrf = 1.0 / (k + rank)
            scores[cid] = scores.get(cid, 0.0) + rrf

            if cid not in meta:
                meta[cid] = {
                    "chunk_id":   cid,
                    "title":      item.get("title", ""),
                    "clean_text": item.get("clean_text", ""),
                    "sources":    [],
                }
            meta[cid]["sources"].append(item.get("source", "?"))

    # Sắp xếp theo RRF score
    ranked = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return [
        {**meta[cid], "rrf_score": round(scores[cid], 6)}
        for cid in ranked[:top_n]
    ]


# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 4: Context Expand
# ─────────────────────────────────────────────────────────────────────────────
async def expand_context(top_chunks: list, meta_db: MetaDB) -> list:
    """
    Lấy nội dung đầy đủ từ PostgreSQL cho top chunks.
    Nếu chunk ngắn (< 150 token) → thêm prev/next.

    Returns:
        list[dict] với clean_text, title, parent_title đã được fill từ PG
    """
    chunk_ids = [c["chunk_id"] for c in top_chunks]
    pg_rows   = await meta_db.get_context(chunk_ids)

    # Index theo chunk_id để lookup nhanh
    pg_map = {r["chunk_id"]: r for r in pg_rows}

    # Chunk IDs cần lấy thêm (prev/next)
    extra_ids = set()
    for row in pg_rows:
        if (row.get("token_count") or 999) < 150:
            if row.get("prev_id"):
                extra_ids.add(row["prev_id"])
            if row.get("next_id"):
                extra_ids.add(row["next_id"])

    # Lấy extra chunks (chỉ những cái chưa có)
    new_ids = [eid for eid in extra_ids if eid not in pg_map]
    if new_ids:
        extra_rows = await meta_db.get_context(new_ids)
        for r in extra_rows:
            pg_map[r["chunk_id"]] = r

    # Build kết quả cuối: ưu tiên clean_text từ PG (đầy đủ hơn Qdrant payload)
    final = []
    seen  = set()
    for chunk in top_chunks:
        cid = chunk["chunk_id"]
        if cid in seen:
            continue
        seen.add(cid)

        pg = pg_map.get(cid, {})
        entry = {
            "chunk_id":     cid,
            "title":        pg.get("title")    or chunk.get("title", ""),
            "clean_text":   pg.get("clean_text") or chunk.get("clean_text", ""),
            "parent_title": pg.get("parent_title", ""),
            "rrf_score":    chunk.get("rrf_score", 0),
            "sources":      chunk.get("sources", []),
        }

        # Thêm prev/next nếu chunk ngắn
        token_count = pg.get("token_count") or 999
        if token_count < 150:
            for extra_id in [pg.get("prev_id"), pg.get("next_id")]:
                if extra_id and extra_id not in seen:
                    extra_pg = pg_map.get(extra_id, {})
                    if extra_pg.get("clean_text"):
                        entry["clean_text"] += "\n\n" + extra_pg["clean_text"]
                        seen.add(extra_id)

        final.append(entry)

    return final


# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 5: Generate Answer
# ─────────────────────────────────────────────────────────────────────────────
async def generate_answer(query: str, context_chunks: list,
                           llm: AsyncLLMClient) -> str:
    """
    Gọi Groq để sinh câu trả lời có trích dẫn nguồn.

    Args:
        query          : câu hỏi gốc của user
        context_chunks : list[dict] từ expand_context
        llm            : AsyncLLMClient

    Returns:
        str — câu trả lời đầy đủ
    """
    # Build context string
    context_parts = []
    for i, chunk in enumerate(context_chunks, 1):
        title = chunk.get("title") or f"Đoạn {i}"
        text  = chunk.get("clean_text", "").strip()
        sources = ", ".join(chunk.get("sources", []))
        context_parts.append(
            f"[{i}] {title} (nguồn: {sources})\n{text}"
        )
    context_str = "\n\n---\n\n".join(context_parts)

    user_prompt = ANSWER_USER.format(query=query, context=context_str)

    return await llm.complete(
        system=ANSWER_SYSTEM,
        user=user_prompt,
        max_tokens=1000,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main search function
# ─────────────────────────────────────────────────────────────────────────────
async def search(query: str, verbose: bool = True) -> dict:
    """
    Pipeline search đầy đủ từ câu hỏi đến câu trả lời.

    Args:
        query   : câu hỏi của user
        verbose : in chi tiết từng bước

    Returns:
        {
          answer        : str,
          query_variants: dict,
          top_chunks    : list[dict],
          latency_ms    : int,
        }
    """
    t0 = time.time()

    # Khởi tạo connections
    meta_db   = MetaDB()
    vector_db = VectorDB()
    kw_db     = KeywordDB()
    graph_db  = GraphDB()
    llm       = AsyncLLMClient()

    await meta_db.connect()
    vector_db.connect()
    kw_db.connect()
    graph_db.connect()

    try:
        if verbose:
            print(f"\n{'='*60}")
            print(f"  🔍 Query: {query}")
            print(f"{'='*60}")

        # ── 1. Query Rewrite ──────────────────────────────────────────────────
        if verbose:
            print("\n[1/5] Query rewrite...")
        variants = await rewrite_query(query, llm)
        if verbose:
            print(f"  original  : {variants['original']}")
            print(f"  technical : {variants['technical']}")
            print(f"  keywords  : {variants['keywords']}")

        # ── 2. Parallel Search ────────────────────────────────────────────────
        if verbose:
            print("\n[2/5] Search song song (Qdrant + ES + Neo4j)...")

        # Chạy 3 search cùng lúc bằng asyncio (ES và Neo4j là sync → thread)
        qdrant_results, es_results, neo4j_results = await asyncio.gather(
            asyncio.to_thread(search_qdrant, vector_db, variants["technical"], SEARCH_TOP_K),
            asyncio.to_thread(search_es,     kw_db,     variants["original"],  SEARCH_TOP_K),
            asyncio.to_thread(search_neo4j,  graph_db,  variants["keywords"],  SEARCH_TOP_K),
        )

        if verbose:
            print(f"  Qdrant    : {len(qdrant_results)} results")
            for r in qdrant_results:
                print(f"    score={r['score']:.4f}  {r['title'][:50]!r}")
            print(f"  ES        : {len(es_results)} results")
            for r in es_results:
                print(f"    score={r['score']:.4f}  {r['title'][:50]!r}")
            print(f"  Neo4j     : {len(neo4j_results)} results")
            for r in neo4j_results:
                print(f"    score={r['score']:.4f}  {r['title'][:50]!r}")

        # ── 3. RRF Merge ──────────────────────────────────────────────────────
        if verbose:
            print("\n[3/5] RRF merge...")
        top_chunks = rrf_merge([qdrant_results, es_results, neo4j_results])

        if verbose:
            print(f"  Top {len(top_chunks)} chunks sau RRF:")
            for i, c in enumerate(top_chunks, 1):
                srcs = "+".join(c["sources"])
                print(f"  {i}. rrf={c['rrf_score']:.5f} [{srcs}]  {c['title'][:50]!r}")

        # ── 4. Context Expand ─────────────────────────────────────────────────
        if verbose:
            print("\n[4/5] Context expand (PostgreSQL)...")
        expanded = await expand_context(top_chunks, meta_db)
        if verbose:
            print(f"  {len(expanded)} chunks với full context")

        # ── 5. Generate Answer ────────────────────────────────────────────────
        if verbose:
            print("\n[5/5] Generate answer (Groq)...")
        answer = await generate_answer(query, expanded, llm)

        latency_ms = int((time.time() - t0) * 1000)

        # Log vào PostgreSQL
        await meta_db.log_search({
            "query_original":  query,
            "query_rewritten": variants,
            "chunks_retrieved": [
                {"chunk_id": c["chunk_id"], "rrf_score": c["rrf_score"],
                 "sources": c["sources"]}
                for c in top_chunks
            ],
            "llm_response": answer,
            "latency_ms":   latency_ms,
        })

        if verbose:
            print(f"\n{'='*60}")
            print(f"  💬 Câu trả lời ({latency_ms}ms):")
            print(f"{'='*60}")
            print(answer)
            print(f"\n{'─'*60}")
            print(f"  📚 Nguồn ({len(expanded)} chunks):")
            for i, c in enumerate(expanded, 1):
                srcs = "+".join(c["sources"])
                print(f"  [{i}] [{srcs}] {c['title'][:60]!r}")
            print(f"{'='*60}\n")

        return {
            "answer":         answer,
            "query_variants": variants,
            "top_chunks":     expanded,
            "latency_ms":     latency_ms,
        }

    finally:
        await meta_db.close()
        graph_db.close()
