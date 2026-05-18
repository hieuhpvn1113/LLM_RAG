# core/enricher.py — LLM Enrichment cho mỗi Level 2 chunk
"""
Gọi Groq LLM để sinh ra metadata phong phú cho mỗi chunk:
  - title                  : tên ngắn gọn
  - summary                : tóm tắt 2-3 câu
  - keywords               : list[str] max 10
  - entities               : list[{name, type}]
  - relations              : list[{from, relation, to}]
  - hypothetical_questions : list[str] 5 câu (quan trọng nhất cho search)

Lưu ý:
  - Groq free tier có rate limit → thêm retry với backoff
  - LLM có thể trả JSON không hợp lệ → có fallback defaults
"""

import json
import re
import asyncio

from llm.client import AsyncLLMClient
from llm.prompts import ENRICHMENT_SYSTEM, ENRICHMENT_USER

# ---------------------------------------------------------------------------
# JSON parser mạnh — xử lý LLM output không chuẩn
# ---------------------------------------------------------------------------
def _parse_llm_json(raw: str) -> dict:
    """
    Parse JSON từ LLM output.
    Xử lý các trường hợp:
      - JSON thuần túy
      - JSON trong markdown code block ```json ... ```
      - JSON với trailing comma
      - Partial JSON (thiếu closing bracket)
    """
    if not raw:
        return {}

    # Strip markdown code block nếu có
    raw = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r'\s*```$', '', raw.strip())
    raw = raw.strip()

    # Thử parse trực tiếp
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Xử lý trailing comma trước } hoặc ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Tìm object JSON đầu tiên trong chuỗi
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


def _default_enrichment() -> dict:
    """Trả về enrichment rỗng khi LLM call thất bại."""
    return {
        "title": "",
        "summary": "",
        "keywords": [],
        "entities": [],
        "relations": [],
        "hypothetical_questions": [],
    }


def _validate_enrichment(data: dict) -> dict:
    """Đảm bảo tất cả các field tồn tại và đúng kiểu."""
    result = _default_enrichment()

    if isinstance(data.get("title"), str):
        result["title"] = data["title"][:200]   # Giới hạn độ dài

    if isinstance(data.get("summary"), str):
        result["summary"] = data["summary"][:1000]

    if isinstance(data.get("keywords"), list):
        result["keywords"] = [str(k) for k in data["keywords"][:10]]

    if isinstance(data.get("entities"), list):
        entities = []
        for e in data["entities"][:20]:
            if isinstance(e, dict) and "name" in e:
                entities.append({
                    "name": str(e["name"])[:100],
                    "type": str(e.get("type", "CONCEPT"))[:20],
                })
        result["entities"] = entities

    if isinstance(data.get("relations"), list):
        relations = []
        for r in data["relations"][:20]:
            if isinstance(r, dict) and "from" in r and "to" in r:
                relations.append({
                    "from":     str(r["from"])[:100],
                    "relation": str(r.get("relation", "RELATES_TO"))[:50],
                    "to":       str(r["to"])[:100],
                })
        result["relations"] = relations

    if isinstance(data.get("hypothetical_questions"), list):
        result["hypothetical_questions"] = [
            str(q)[:300] for q in data["hypothetical_questions"][:5]
        ]

    return result


# ---------------------------------------------------------------------------
# Main enrichment function (async)
# ---------------------------------------------------------------------------
async def enrich_chunk(chunk_text: str, llm: AsyncLLMClient,
                       max_retries: int = 3) -> dict:
    """
    Gọi Groq LLM để enrich 1 chunk text.

    Args:
        chunk_text  : nội dung của chunk (clean_text)
        llm         : AsyncLLMClient instance (tái sử dụng, không tạo mới mỗi lần)
        max_retries : số lần retry khi LLM trả lỗi hoặc JSON invalid

    Returns:
        dict với keys: title, summary, keywords, entities, relations, hypothetical_questions
    """
    # Giới hạn text gửi lên LLM để tránh vượt context window
    MAX_CHARS = 3000
    if len(chunk_text) > MAX_CHARS:
        chunk_text = chunk_text[:MAX_CHARS] + '...'

    user_prompt = ENRICHMENT_USER.format(chunk_text=chunk_text)

    for attempt in range(1, max_retries + 1):
        try:
            raw = await llm.complete(
                system=ENRICHMENT_SYSTEM,
                user=user_prompt,
                max_tokens=1200,
            )
            data = _parse_llm_json(raw)
            if data:
                return _validate_enrichment(data)

            # JSON rỗng → retry
            if attempt < max_retries:
                await asyncio.sleep(1)

        except Exception as e:
            err_msg = str(e).lower()

            # Rate limit → đợi lâu hơn
            if 'rate_limit' in err_msg or '429' in err_msg:
                wait = 20 * attempt
                print(f"    ⏳ Rate limit — đợi {wait}s (attempt {attempt}/{max_retries})")
                await asyncio.sleep(wait)
            else:
                print(f"    ⚠️  LLM error attempt {attempt}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 * attempt)

    print("    ⚠️  Enrichment thất bại — dùng fallback defaults")
    return _default_enrichment()
