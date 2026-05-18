# db/meta_db.py — PostgreSQL Meta Table client
import asyncpg
import json
from config import PG_DSN


class MetaDB:
    """PostgreSQL client cho Meta Table (documents + chunks + search_logs)"""

    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)
        print("✅ PostgreSQL connected")

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ── Documents ──────────────────────────────────────────────────────────────

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

    # ── Chunks ─────────────────────────────────────────────────────────────────

    async def insert_chunk(self, chunk: dict) -> str:
        """
        Insert chunk vào PostgreSQL.
        Nếu chunk đã có 'chunk_id' (pre-assigned UUID) → dùng luôn.
        Nếu không → để PostgreSQL tự generate.
        """
        async with self.pool.acquire() as conn:
            if chunk.get("chunk_id"):
                # Dùng UUID đã assign sẵn (quan trọng để set parent_id đúng)
                row = await conn.fetchrow(
                    """
                    INSERT INTO chunks (
                        chunk_id, doc_id, level, parent_id, prev_id, next_id, seq_no,
                        raw_text, clean_text, token_count, source_file, char_start, char_end
                    )
                    VALUES ($1::UUID,$2,$3,$4::UUID,$5::UUID,$6::UUID,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (chunk_id) DO NOTHING
                    RETURNING chunk_id::TEXT
                    """,
                    chunk["chunk_id"],
                    chunk["doc_id"], chunk["level"],
                    chunk.get("parent_id"), chunk.get("prev_id"), chunk.get("next_id"),
                    chunk["seq_no"], chunk["raw_text"], chunk.get("clean_text"),
                    chunk.get("token_count"), chunk.get("source_file"),
                    chunk.get("char_start"), chunk.get("char_end")
                )
                return row["chunk_id"] if row else chunk["chunk_id"]
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO chunks (
                        doc_id, level, parent_id, prev_id, next_id, seq_no,
                        raw_text, clean_text, token_count, source_file, char_start, char_end
                    )
                    VALUES ($1,$2,$3::UUID,$4::UUID,$5::UUID,$6,$7,$8,$9,$10,$11,$12)
                    RETURNING chunk_id::TEXT
                    """,
                    chunk["doc_id"], chunk["level"],
                    chunk.get("parent_id"), chunk.get("prev_id"), chunk.get("next_id"),
                    chunk["seq_no"], chunk["raw_text"], chunk.get("clean_text"),
                    chunk.get("token_count"), chunk.get("source_file"),
                    chunk.get("char_start"), chunk.get("char_end")
                )
                return row["chunk_id"]

    async def update_chunk_links(self, chunk_id: str, prev_id: str | None, next_id: str | None):
        """Cập nhật linked list (prev_id / next_id) sau khi tất cả chunks đã được insert."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET prev_id = $2::UUID, next_id = $3::UUID, updated_at = NOW()
                WHERE chunk_id = $1::UUID
                """,
                chunk_id, prev_id, next_id
            )

    async def update_enrichment(self, chunk_id: str, enrichment: dict):
        """Cập nhật sau khi LLM enrichment xong."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET title = $2, summary = $3,
                    keywords = $4::JSONB, entities = $5::JSONB,
                    hypothetical_questions = $6::JSONB, relations = $7::JSONB,
                    updated_at = NOW()
                WHERE chunk_id = $1::UUID
                """,
                chunk_id,
                enrichment.get("title", ""),
                enrichment.get("summary", ""),
                json.dumps(enrichment.get("keywords", [])),
                json.dumps(enrichment.get("entities", [])),
                json.dumps(enrichment.get("hypothetical_questions", [])),
                json.dumps(enrichment.get("relations", []))
            )

    async def mark_embedded(self, chunk_id: str, model: str):
        """Đánh dấu chunk đã được embed xong."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chunks
                SET embed_status = 'done', embed_model = $2, updated_at = NOW()
                WHERE chunk_id = $1::UUID
                """,
                chunk_id, model
            )

    async def get_context(self, chunk_ids: list) -> list:
        """Lấy chunks + parent để expand context (dùng trong Phase 3 search)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.chunk_id::TEXT, c.doc_id::TEXT, c.level, c.seq_no,
                       c.clean_text, c.title, c.summary, c.token_count,
                       c.parent_id::TEXT, c.prev_id::TEXT, c.next_id::TEXT,
                       p.clean_text AS parent_text, p.title AS parent_title
                FROM chunks c
                LEFT JOIN chunks p ON c.parent_id = p.chunk_id
                WHERE c.chunk_id = ANY($1::UUID[])
                ORDER BY c.seq_no
                """,
                chunk_ids
            )
            return [dict(r) for r in rows]

    async def get_prev_next(self, chunk_id: str) -> dict:
        """Lấy chunk trước và sau (dùng khi context quá ngắn)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT prev_id::TEXT, next_id::TEXT
                FROM chunks
                WHERE chunk_id = $1::UUID
                """,
                chunk_id
            )
            return dict(row) if row else {}

    async def get_pending_embed(self, limit: int = 50) -> list:
        """Lấy Level 2 chunks chưa embed — dùng idx_chunks_embed_status."""
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

    async def log_search(self, log: dict):
        """Ghi log search vào PostgreSQL."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO search_logs
                    (query_original, query_rewritten, chunks_retrieved, llm_response, latency_ms)
                VALUES ($1, $2::JSONB, $3::JSONB, $4, $5)
                """,
                log["query_original"],
                json.dumps(log.get("query_rewritten", {})),
                json.dumps(log.get("chunks_retrieved", [])),
                log.get("llm_response", ""),
                log.get("latency_ms", 0)
            )
