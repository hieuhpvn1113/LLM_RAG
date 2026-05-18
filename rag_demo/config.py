# config.py — Cấu hình toàn bộ hệ thống RAG
import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM ────────────────────────────────────────────────────
# Groq free tier: https://console.groq.com
# Các model miễn phí khả dụng: llama-3.3-70b-versatile, gemma2-9b-it, mixtral-8x7b-32768
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL    = "llama-3.3-70b-versatile"   # Groq free model — nhanh & mạnh

# ── Embedding (local, hoàn toàn miễn phí) ──────────────────
# Dùng sentence-transformers chạy local, không cần API key
EMBED_MODEL = "all-MiniLM-L6-v2"   # 384 dims, nhẹ & nhanh cho demo
# Thay bằng "BAAI/bge-base-en-v1.5" (768 dims) nếu muốn chất lượng cao hơn

# ── Chunking ────────────────────────────────────────────────
CHUNK_SIZE_SECTION   = 1000   # token — Level 1 (Section)
CHUNK_SIZE_PARAGRAPH = 512    # token — Level 2 (Paragraph, unit embed)
CHUNK_OVERLAP        = 64     # token overlap giữa các chunk
SEMANTIC_THRESHOLD   = 0.4    # cosine distance để cắt semantic

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
VECTOR_DIM        = 384   # khớp với all-MiniLM-L6-v2
                          # đổi thành 768 nếu dùng bge-base-en-v1.5

# ── Elasticsearch ───────────────────────────────────────────
ES_URL   = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = "rag_chunks"

# ── Neo4j ───────────────────────────────────────────────────
NEO4J_URL      = os.getenv("NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# ── Search ──────────────────────────────────────────────────
SEARCH_TOP_K = 3    # Mỗi DB trả về top 3
FINAL_TOP_K  = 6    # Sau RRF chọn top 6
RRF_K        = 60   # Hằng số RRF chuẩn

# ── Hybrid Search weights (Qdrant) ──────────────────────────
DENSE_WEIGHT  = 0.7
SPARSE_WEIGHT = 0.3
