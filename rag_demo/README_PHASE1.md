# RAG System — Phase 1: Setup

## Bước 1: Cài đặt Python packages
```bash
cd rag_demo
pip install -r requirements.txt
```

## Bước 2: Cấu hình .env
```bash
# Sửa file .env — điền API keys thật
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
```

## Bước 3: Khởi động Docker (4 databases)
```bash
docker-compose up -d
```

Chờ ~30s để tất cả service healthy.

## Bước 4: Kiểm tra kết nối
```bash
python test_connections.py
```

Output mong muốn:
```
✅ PostgreSQL OK
✅ Qdrant OK
✅ Elasticsearch OK
✅ Neo4j OK
✅ Table "documents" exists
✅ Table "chunks" exists
✅ Table "search_logs" exists
📊 Total indexes: 15
🎉 Phase 1 COMPLETE!
```

## Bước 5: Truy cập UI (optional)
- Neo4j Browser: http://localhost:7474
- Elasticsearch: http://localhost:9200
- Qdrant Dashboard: http://localhost:6333/dashboard
- PostgreSQL: psql -h localhost -U rag_user -d rag_db

## Các lệnh hữu ích
```bash
# Xem logs Docker
docker-compose logs -f

# Restart service cụ thể
docker-compose restart elasticsearch

# Kiểm tra PostgreSQL indexes
psql -h localhost -U rag_user -d rag_db -c "\\di"

# Dừng tất cả
docker-compose down
```
