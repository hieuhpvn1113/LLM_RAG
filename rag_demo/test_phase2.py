# test_phase2.py — Kiểm tra từng bước Phase 2
import asyncio
from pathlib import Path


def test_chunker():
    print("=" * 55)
    print("  TEST 1: Chunker")
    print("=" * 55)
    from core.chunker import hierarchical_split, semantic_split

    text = Path("data/input.txt").read_text(encoding="utf-8")
    print(f"  File: data/input.txt ({len(text):,} chars)\n")

    # Level 1
    sections = hierarchical_split(text, "test-doc-id", "input.txt")
    print(f"  Level 1 Sections: {len(sections)}")
    for s in sections:
        print(f"    [{s['seq_no']:2d}] {s['token_count']:4d} tok — {s['clean_text'][:55].strip()!r}")

    # Level 2
    print()
    all_l2 = []
    for section in sections:
        l2 = semantic_split(section, "test-doc-id")
        all_l2.extend(l2)
        print(f"    Section {section['seq_no']:2d} → {len(l2):2d} paragraphs")

    print(f"\n  Tổng Level 2 chunks: {len(all_l2)}")
    print(f"  Token range: {min(c['token_count'] for c in all_l2)} – {max(c['token_count'] for c in all_l2)}")
    print("  ✅ Chunker OK\n")
    return sections, all_l2


def test_embedder(chunks):
    print("=" * 55)
    print("  TEST 2: Embedder")
    print("=" * 55)
    from core.embedder import embed_batch

    texts = [c["clean_text"] for c in chunks[:3]]  # Test với 3 chunks đầu
    vectors = embed_batch(texts)
    print(f"  Embedded {len(vectors)} chunks")
    print(f"  Vector dim: {len(vectors[0])}")
    print(f"  Sample norm: {sum(v**2 for v in vectors[0])**0.5:.4f} (should be ~1.0)")
    print("  ✅ Embedder OK\n")
    return vectors


async def test_enricher(chunk):
    print("=" * 55)
    print("  TEST 3: Enricher (LLM — Groq)")
    print("=" * 55)
    from core.enricher import enrich_chunk
    from llm.client import AsyncLLMClient

    llm = AsyncLLMClient()
    print(f"  Enriching: {chunk['clean_text'][:80]!r}...")
    result = await enrich_chunk(chunk["clean_text"], llm)

    print(f"  title     : {result['title']}")
    print(f"  summary   : {result['summary'][:80]}...")
    print(f"  keywords  : {result['keywords']}")
    print(f"  entities  : {result['entities']}")
    print(f"  hypo Qs   : {len(result['hypothetical_questions'])} câu")
    for q in result["hypothetical_questions"]:
        print(f"    - {q}")
    print("  ✅ Enricher OK\n")
    return result


async def main():
    print("\n" + "=" * 55)
    print("  Phase 2 — Component Tests")
    print("=" * 55 + "\n")

    # Test 1: Chunker
    sections, l2_chunks = test_chunker()

    # Test 2: Embedder
    test_embedder(l2_chunks)

    # Test 3: Enricher (gọi LLM thật — tốn ~2s)
    await test_enricher(l2_chunks[0])

    print("=" * 55)
    print("  Tất cả tests PASSED — Sẵn sàng chạy full ingest!")
    print("  Chạy: python main.py ingest data/input.txt")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
