# core/embedder.py — Tạo vector embedding (local, miễn phí)
# Model: all-MiniLM-L6-v2 (sentence-transformers) — 384 dims
# Chạy hoàn toàn local, không cần API key
from sentence_transformers import SentenceTransformer
from config import EMBED_MODEL

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load model lần đầu gọi, cache lại cho các lần sau."""
    global _model
    if _model is None:
        # Some multilingual models (e.g. gte-multilingual-base) require custom HF code.
        _model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    return _model


def embed_text(text: str) -> list[float]:
    """Trả về dense vector 384 chiều cho một đoạn text."""
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed nhiều đoạn text cùng lúc (hiệu quả hơn gọi từng cái)."""
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return vectors.tolist()
