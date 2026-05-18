# core/chunker.py — Semantic + Hierarchical Chunking
"""
Chiến lược 2 cấp:
  Level 1 (Section)   — ~1000 token  — split bởi heading / paragraph boundary
  Level 2 (Paragraph) — ~512  token  — semantic split bằng cosine distance giữa câu

Thứ tự gọi:
  sections  = hierarchical_split(full_text, doc_id, source_file)
  l2_chunks = semantic_split(section, doc_id)   # gọi cho từng section
"""

import re
import uuid
import numpy as np
import tiktoken

from config import CHUNK_SIZE_SECTION, CHUNK_SIZE_PARAGRAPH, CHUNK_OVERLAP, SEMANTIC_THRESHOLD

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
_enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(_enc.encode(text))

def clean_text(text: str) -> str:
    """Loại bỏ noise: nhiều dòng trống, nhiều dấu cách, BOM."""
    text = text.replace('\ufeff', '')                  # BOM UTF-8
    text = re.sub(r'\r\n', '\n', text)                 # Windows line endings
    text = re.sub(r'\n{3,}', '\n\n', text)             # Max 2 consecutive newlines
    text = re.sub(r'[ \t]+', ' ', text)                # Normalize spaces/tabs
    text = re.sub(r' \n', '\n', text)                  # Trailing spaces before newline
    return text.strip()


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------
def _split_sentences(text: str) -> list:
    """
    Tách văn bản thành danh sách câu.
    Ưu tiên NLTK; fallback sang regex nếu NLTK chưa có punkt model.
    """
    try:
        import nltk
        try:
            return nltk.sent_tokenize(text)
        except LookupError:
            nltk.download('punkt', quiet=True)
            nltk.download('punkt_tab', quiet=True)
            return nltk.sent_tokenize(text)
    except Exception:
        # Regex fallback: cắt tại . ! ? theo sau là khoảng trắng + chữ hoa / chữ số
        parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÀÂĂĐÊÔƠƯA-Z0-9\"\'])', text)
        return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Cosine distance
# ---------------------------------------------------------------------------
def _cosine_distance(v1: list, v2: list) -> float:
    a, b = np.array(v1), np.array(v2)
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(1.0 - np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Heading detector
# ---------------------------------------------------------------------------
_HEADING_RE = re.compile(
    r'^(?:'
    r'#{1,3}\s.+'                           # Markdown: # Heading
    r'|[A-Z][A-Z0-9\s\-:]{4,}$'            # ALL CAPS title (≥ 5 chars)
    r'|[=\-]{3,}'                           # Separator: === hoặc ---
    r')$',
    re.MULTILINE
)

def _is_heading(para: str) -> bool:
    para = para.strip()
    if len(para) > 120:        # Tiêu đề không quá dài
        return False
    return bool(_HEADING_RE.match(para))


# ---------------------------------------------------------------------------
# STEP 1: Hierarchical Split → Level 1 (Sections)
# ---------------------------------------------------------------------------
def hierarchical_split(text: str, doc_id: str, source_file: str) -> list:
    """
    Trả về list[dict] — mỗi dict là 1 Level 1 chunk (Section).
    Mỗi chunk đã có 'chunk_id' UUID được assign sẵn.

    Chiến lược:
      1. Tách text thành paragraphs (split by \\n\\n)
      2. Khi gặp heading → bắt đầu section mới
      3. Khi token count vượt CHUNK_SIZE_SECTION → bắt đầu section mới
      4. Cuối cùng merge các section quá nhỏ (< 100 token) vào section trước
    """
    text = clean_text(text)
    raw_paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]

    if not raw_paragraphs:
        return []

    # Nhóm paragraphs thành sections
    sections_raw = []          # list of str
    current_parts = []
    current_tokens = 0

    for para in raw_paragraphs:
        para_tokens = count_tokens(para)
        is_heading   = _is_heading(para)

        # Bắt đầu section mới khi: gặp heading HOẶC overflow token
        if (is_heading or current_tokens + para_tokens > CHUNK_SIZE_SECTION) and current_parts:
            sections_raw.append('\n\n'.join(current_parts))
            current_parts = []
            current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        sections_raw.append('\n\n'.join(current_parts))

    # Merge section quá nhỏ (< 100 token) vào section trước
    merged = []
    for s in sections_raw:
        if merged and count_tokens(s) < 100:
            merged[-1] = merged[-1] + '\n\n' + s
        else:
            merged.append(s)

    # Tạo chunk dicts với pre-assigned UUIDs
    chunks = []
    char_cursor = 0
    for idx, section_text in enumerate(merged):
        if not section_text.strip():
            continue
        cleaned = clean_text(section_text)
        # Tìm vị trí char trong text gốc (tìm từ cursor để tránh false positive)
        pos = text.find(section_text, char_cursor)
        char_start = pos if pos != -1 else 0
        char_end   = char_start + len(section_text)
        char_cursor = char_end

        chunks.append({
            'chunk_id':    str(uuid.uuid4()),
            'doc_id':      doc_id,
            'level':       1,
            'parent_id':   None,
            'prev_id':     None,
            'next_id':     None,
            'seq_no':      idx,
            'raw_text':    section_text,
            'clean_text':  cleaned,
            'token_count': count_tokens(cleaned),
            'source_file': source_file,
            'char_start':  char_start,
            'char_end':    char_end,
        })

    # Fallback: nếu không tách được gì
    if not chunks:
        cleaned = clean_text(text)
        chunks.append({
            'chunk_id':    str(uuid.uuid4()),
            'doc_id':      doc_id,
            'level':       1,
            'parent_id':   None,
            'prev_id':     None,
            'next_id':     None,
            'seq_no':      0,
            'raw_text':    text,
            'clean_text':  cleaned,
            'token_count': count_tokens(cleaned),
            'source_file': source_file,
            'char_start':  0,
            'char_end':    len(text),
        })

    return chunks


# ---------------------------------------------------------------------------
# STEP 2: Semantic Split → Level 2 (Paragraphs)
# ---------------------------------------------------------------------------
def semantic_split(section: dict, doc_id: str) -> list:
    """
    Nhận 1 Level 1 section dict, trả về list[dict] Level 2 chunks.

    Chiến lược:
      1. Tách thành câu
      2. Embed tất cả câu bằng all-MiniLM-L6-v2 (batch)
      3. Tính cosine distance giữa câu liên tiếp
      4. Cắt tại điểm có distance > SEMANTIC_THRESHOLD
      5. Gộp các group quá nhỏ
      6. Thêm overlap ~CHUNK_OVERLAP token ở đầu mỗi chunk
      7. Gán prev_id / next_id để tạo linked list
    """
    from core.embedder import embed_batch   # lazy import — model load lần đầu

    text        = section['clean_text']
    parent_id   = section['chunk_id']
    source_file = section.get('source_file', '')
    # seq_no cấp 2: section_seq * 1000 + paragraph_index
    base_seq    = section['seq_no'] * 1000

    # Nếu section đủ ngắn → giữ nguyên làm 1 Level 2 chunk
    if count_tokens(text) <= CHUNK_SIZE_PARAGRAPH:
        cid = str(uuid.uuid4())
        return [{
            'chunk_id':    cid,
            'doc_id':      doc_id,
            'level':       2,
            'parent_id':   parent_id,
            'prev_id':     None,
            'next_id':     None,
            'seq_no':      base_seq,
            'raw_text':    text,
            'clean_text':  text,
            'token_count': count_tokens(text),
            'source_file': source_file,
        }]

    sentences = _split_sentences(text)
    if not sentences:
        return []

    # Embed tất cả câu 1 lần (batch — nhanh hơn nhiều so với từng câu)
    vectors = embed_batch(sentences)

    # Tìm điểm cắt ngữ nghĩa
    # Dùng cửa sổ 2 câu để giảm noise: so sánh trung bình window trái vs phải
    cut_indices = set()
    WIN = 2   # Window size
    for i in range(WIN, len(sentences) - WIN):
        v_left  = np.mean([vectors[j] for j in range(max(0, i-WIN), i)], axis=0)
        v_right = np.mean([vectors[j] for j in range(i, min(len(vectors), i+WIN))], axis=0)
        dist = _cosine_distance(v_left.tolist(), v_right.tolist())
        if dist > SEMANTIC_THRESHOLD:
            cut_indices.add(i)

    # Nhóm câu thành groups theo điểm cắt
    groups = []
    start = 0
    for cut in sorted(cut_indices):
        if cut > start:
            groups.append(sentences[start:cut])
        start = cut
    if start < len(sentences):
        groups.append(sentences[start:])

    if not groups:
        groups = [sentences]

    # Gộp groups quá nhỏ (< 80 token) vào group kề
    merged_groups = []
    for g in groups:
        g_text = ' '.join(g)
        if merged_groups and count_tokens(g_text) < 80:
            merged_groups[-1] += g       # gộp vào group trước
        else:
            merged_groups.append(list(g))

    if not merged_groups:
        merged_groups = [sentences]

    # Tạo chunks với overlap
    chunks = []
    overlap_text = ''

    for idx, group in enumerate(merged_groups):
        body = ' '.join(group)
        # Prepend overlap từ chunk trước
        chunk_text = (overlap_text.strip() + ' ' + body).strip() if overlap_text else body

        # Nếu chunk vượt CHUNK_SIZE_PARAGRAPH → cắt cứng ở giới hạn token
        tokens = _enc.encode(chunk_text)
        if len(tokens) > CHUNK_SIZE_PARAGRAPH:
            chunk_text = _enc.decode(tokens[:CHUNK_SIZE_PARAGRAPH])

        # Chuẩn bị overlap cho chunk tiếp theo
        final_tokens = _enc.encode(chunk_text)
        if len(final_tokens) > CHUNK_OVERLAP:
            overlap_text = _enc.decode(final_tokens[-CHUNK_OVERLAP:])
        else:
            overlap_text = chunk_text

        chunks.append({
            'chunk_id':    str(uuid.uuid4()),
            'doc_id':      doc_id,
            'level':       2,
            'parent_id':   parent_id,
            'prev_id':     None,   # điền sau khi có đủ danh sách
            'next_id':     None,
            'seq_no':      base_seq + idx,
            'raw_text':    chunk_text,
            'clean_text':  chunk_text,
            'token_count': count_tokens(chunk_text),
            'source_file': source_file,
        })

    # Gán prev_id / next_id → linked list trong cùng 1 section
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk['prev_id'] = chunks[i - 1]['chunk_id']
        if i < len(chunks) - 1:
            chunk['next_id'] = chunks[i + 1]['chunk_id']

    return chunks
