# config.py — Cấu hình toàn bộ hệ thống RAG
import os
from dotenv import load_dotenv

load_dotenv()

# ── Groq API ────────────────────────────────────────────────
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL  = "https://api.groq.com/openai/v1"
GROQ_MODEL     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Chunking mode ───────────────────────────────────────────
CHUNKING_MODE = os.getenv("CHUNKING_MODE", "llm")

# ── Embedding ───────────────────────────────────────────────
EMBED_MODEL = "intfloat/multilingual-e5-base"   # 768 dims

# ── Chunking ────────────────────────────────────────────────
CHUNK_SIZE_PARAGRAPH = 512    # token — soft limit, flush tại ranh giới câu
SEMANTIC_THRESHOLD   = 0.24   # ngưỡng cosine distance để cắt semantic unit

# ── Hypothetical Questions ──────────────────────────────────
NUM_HYPO_QUESTIONS = 5

# ── PostgreSQL ──────────────────────────────────────────────
PG_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_db"
)

# ── Qdrant ──────────────────────────────────────────────────
QDRANT_URL        = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = "rag_chunks"
VECTOR_DIM        = 768

# ── Elasticsearch ───────────────────────────────────────────
ES_URL   = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = "rag_chunks"

# ── Neo4j ───────────────────────────────────────────────────
NEO4J_URL      = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# ── Search ──────────────────────────────────────────────────
SEARCH_TOP_K  = 3     # số kết quả mỗi DB
FINAL_TOP_K   = 6     # số chunk sau RRF merge (cho LLM)
RRF_K         = 60    # hằng số RRF

# Ngưỡng RRF tối thiểu để 1 chunk cha được hiển thị trong nguồn dữ liệu.
# 1/(60+1) ≈ 0.0164 = xuất hiện ở 1 DB rank 1
# 2/(60+1) ≈ 0.0328 = xuất hiện ở 2 DB rank 1, hoặc 1 DB với rank cao
# Đặt 0.025 → lọc bỏ các chunk chỉ xuất hiện ở 1 DB với rank thấp
SOURCE_MIN_RRF = float(os.getenv("SOURCE_MIN_RRF", "0.025"))

# ── Hybrid Search weights (Qdrant) ──────────────────────────
DENSE_WEIGHT  = 0.7
SPARSE_WEIGHT = 0.3
