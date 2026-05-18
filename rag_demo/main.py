# main.py — Entry point: Ingest + Query
"""
Cách dùng:
  python main.py ingest data/input.txt
  python main.py query "RAG là gì?"
"""

import asyncio
import sys
from pathlib import Path


def cmd_ingest(file_path: str):
    from core.ingestor import ingest_file
    doc_id = asyncio.run(ingest_file(file_path))
    print(f"\n✅ Ingest xong — doc_id = {doc_id}")
    print('Giờ thử: python main.py query "RAG là gì?"')


def cmd_query(query: str):
    from core.retriever import search
    asyncio.run(search(query, verbose=True))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python main.py ingest <file.txt>")
        print('  python main.py query  "câu hỏi"')
        sys.exit(1)

    command  = sys.argv[1].lower()
    argument = " ".join(sys.argv[2:])   # hỗ trợ query nhiều từ không cần quotes

    if command == "ingest":
        if not Path(argument).exists():
            print(f"❌ File không tồn tại: {argument}")
            sys.exit(1)
        cmd_ingest(argument)

    elif command == "query":
        cmd_query(argument)

    else:
        print(f"❌ Lệnh không hợp lệ: {command}  (dùng: ingest | query)")
        sys.exit(1)
