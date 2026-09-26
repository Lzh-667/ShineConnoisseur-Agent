"""真实中间件连通性与基础读写测试。

默认跳过；设置 RUN_INTEGRATION=1 后运行，CI 会启动隔离的服务容器。
"""

import json
import os
import uuid

import pytest

from app.services import es_client, mysql
from app.services.redis_client import get_redis
from app.services.session_store import delete_session, get_session, list_sessions, touch_session

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1",
                       reason="set RUN_INTEGRATION=1 to run live dependency tests"),
]


def test_mysql_connection_executes_real_query():
    rows = mysql._rows("SELECT 1 AS value")
    assert rows == [{"value": 1}]


def test_redis_connection_and_session_round_trip():
    redis = get_redis()
    assert redis.ping()

    thread_id = uuid.uuid4().hex
    owner_id = f"integration:{uuid.uuid4().hex}"
    touch_session(thread_id, owner_id, "集成测试会话")
    try:
        assert get_session(thread_id)["ownerId"] == owner_id
        sessions, total = list_sessions(owner_id)
        assert total == 1
        assert sessions[0]["threadId"] == thread_id
    finally:
        delete_session(thread_id, owner_id)


def test_elasticsearch_connection_is_reachable():
    assert es_client.ping()


def test_real_es_hybrid_search_reaches_semantic_tool(monkeypatch):
    """真实 ES 写入→BM25/KNN/RRF→LangChain 工具 JSON，外部模型使用固定向量替代。"""
    from app.rag import es_hybrid
    from app.rag.es_hybrid import MOVIE_VEC_INDEX
    from app.tools import TOOLS_BY_NAME

    es = es_client.get_es()
    created_index = not es.indices.exists(index=MOVIE_VEC_INDEX)
    if created_index:
        es.indices.create(index=MOVIE_VEC_INDEX, mappings={"properties": {
            "id": {"type": "long"},
            "title": {"type": "text"},
            "originalTitle": {"type": "text"},
            "director": {"type": "text"},
            "actors": {"type": "text"},
            "genre": {"type": "keyword"},
            "region": {"type": "keyword"},
            "releaseYear": {"type": "integer"},
            "summary": {"type": "text"},
            "status": {"type": "integer"},
            "content_embedding": {
                "type": "dense_vector", "dims": 1024, "index": True,
                "similarity": "cosine",
            },
        }})

    doc_id = 9_900_001
    movie = {
        "id": doc_id,
        "title": "CodexRagPipeline 测试电影",
        "originalTitle": "CodexRagPipeline",
        "director": "Integration Test",
        "actors": "Test Actor",
        "genre": "科幻",
        "region": "测试地区",
        "releaseDate": "2026-01-01",
        "summary": "codexragpipeline 独占检索词，用于验证完整 RAG 工具链。",
        "status": 1,
        "rating": 9.0,
    }
    fixed_vector = [1.0] + [0.0] * 1023
    monkeypatch.setattr(es_hybrid, "embed_texts", lambda texts: [fixed_vector for _ in texts])
    monkeypatch.setattr(
        "app.tools.rag_tools.mysql.get_movies_by_ids",
        lambda ids: [movie] if doc_id in ids else [],
    )

    try:
        assert es_hybrid.index_movies([movie]) == 1
        es.indices.refresh(index=MOVIE_VEC_INDEX)
        payload = json.loads(TOOLS_BY_NAME["semantic_search"].invoke({
            "query": "codexragpipeline",
            "index": "movie",
            "top_k": 3,
        }))
        assert payload["results"][0]["id"] == doc_id
        assert payload["results"][0]["type"] == "movie"
    finally:
        if created_index:
            es.indices.delete(index=MOVIE_VEC_INDEX)
        else:
            es.delete_by_query(
                index=MOVIE_VEC_INDEX,
                query={"term": {"id": doc_id}},
                refresh=True,
            )
