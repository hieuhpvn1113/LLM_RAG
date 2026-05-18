#!/usr/bin/env python3
"""
test_connections.py — Kiểm tra kết nối tất cả DB (Phase 1 verification)
Chạy: python test_connections.py
"""

import asyncio
import sys
import requests


async def test_postgresql():
    print("\n🔍 Testing PostgreSQL...")
    try:
        import asyncpg
        from config import PG_DSN
        conn = await asyncpg.connect(PG_DSN)
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        print(f"  ✅ PostgreSQL OK — {version[:40]}...")
        return True
    except Exception as e:
        print(f"  ❌ PostgreSQL FAILED: {e}")
        return False


async def test_qdrant():
    print("\n🔍 Testing Qdrant...")
    try:
        from config import QDRANT_URL
        r = requests.get(f"{QDRANT_URL}/healthz", timeout=5)
        if r.status_code == 200:
            print(f"  ✅ Qdrant OK — {QDRANT_URL}")
            return True
        else:
            print(f"  ❌ Qdrant returned {r.status_code}")
            return False
    except Exception as e:
        print(f"  ❌ Qdrant FAILED: {e}")
        return False


async def test_elasticsearch():
    print("\n🔍 Testing Elasticsearch...")
    try:
        from config import ES_URL
        r = requests.get(f"{ES_URL}", timeout=5)
        data = r.json()
        version = data.get("version", {}).get("number", "?")
        print(f"  ✅ Elasticsearch OK — v{version}")
        return True
    except Exception as e:
        print(f"  ❌ Elasticsearch FAILED: {e}")
        return False


async def test_neo4j():
    print("\n🔍 Testing Neo4j...")
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URL, NEO4J_USER, NEO4J_PASSWORD
        driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 AS n")
            result.single()
        driver.close()
        print(f"  ✅ Neo4j OK — {NEO4J_URL}")
        return True
    except Exception as e:
        print(f"  ❌ Neo4j FAILED: {e}")
        return False


async def test_postgres_tables():
    print("\n🔍 Checking PostgreSQL tables...")
    try:
        import asyncpg
        from config import PG_DSN
        conn = await asyncpg.connect(PG_DSN)
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        table_names = [t["tablename"] for t in tables]
        required = ["documents", "chunks", "search_logs"]
        for t in required:
            if t in table_names:
                print(f"  ✅ Table \"{t}\" exists")
            else:
                print(f"  ❌ Table \"{t}\" MISSING — chạy migration!")
        indexes = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY indexname"
        )
        print(f"  📊 Total indexes: {len(indexes)}")
        await conn.close()
        return all(t in table_names for t in required)
    except Exception as e:
        print(f"  ❌ Table check FAILED: {e}")
        return False


async def main():
    print("=" * 55)
    print("  RAG System — Phase 1 Connection Test")
    print("=" * 55)

    results = await asyncio.gather(
        test_postgresql(),
        test_qdrant(),
        test_elasticsearch(),
        test_neo4j(),
    )

    if results[0]:  # PostgreSQL OK
        await test_postgres_tables()

    print("\n" + "=" * 55)
    passed = sum(results)
    total = len(results)
    print(f"  Result: {passed}/{total} services connected")
    if passed == total:
        print("  🎉 Phase 1 COMPLETE! Tiến hành Phase 2.")
    else:
        print("  ⚠️  Một số service chưa kết nối — kiểm tra Docker.")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
