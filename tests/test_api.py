"""API 层测试：TestClient 覆盖 chat/sessions/profile/admin，mock 全部外部依赖。"""

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.config.settings import settings
from app.services import mysql

USER = {"userId": 1, "username": "u", "nickname": "n", "avatar": "", "token": "tok"}
THREAD_ID = "a" * 32


class FakeAgent:
    """模拟 create_agent 产物，只实现 chat 用到的 ainvoke/astream。"""

    def __init__(self, reply="你好，我是光影助手", messages=None, stream_events=None):
        self.reply = reply
        self.messages = messages
        self.stream_events = stream_events or []

    async def ainvoke(self, messages, config=None, context=None):
        msgs = self.messages or [AIMessage(content=self.reply)]
        return {"messages": msgs}

    async def astream(self, messages, config=None, context=None, stream_mode=None):
        for ev in self.stream_events:
            yield ev


@pytest.fixture
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "chat_rate_limit", 100)


def _patch_chat_deps(monkeypatch, fake_redis, agent):
    monkeypatch.setattr("app.api.chat.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.chat.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.chat.touch_session", lambda *a, **kw: None)
    monkeypatch.setattr("app.api.chat.get_session", lambda tid: {"ownerId": "user:1"})
    monkeypatch.setattr("app.api.chat.get_agent", lambda: agent)


# ---------- /chat 非流式 ----------


def test_chat_ok(client, monkeypatch, fake_redis, no_rate_limit):
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent())
    resp = client.post("/api/agent/chat",
                       json={"threadId": THREAD_ID, "message": "推荐一部电影"},
                       headers={"authorization": "tok"})
    body = resp.json()
    assert resp.status_code == 200 and body["success"]
    assert body["data"]["threadId"] == THREAD_ID
    assert "光影助手" in body["data"]["reply"]


def test_chat_new_thread_id(client, monkeypatch, fake_redis, no_rate_limit):
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent())
    body = client.post("/api/agent/chat", json={"message": "hi"}).json()
    assert body["success"] and len(body["data"]["threadId"]) == 32


def test_chat_rate_limited(client, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "chat_rate_limit", 10)
    monkeypatch.setattr("app.api.chat.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.chat.get_redis", lambda: fake_redis)
    fake_redis.counters[f"agent:rate:user:{USER['userId']}"] = 99
    body = client.post("/api/agent/chat", json={"message": "hi"}).json()
    assert not body["success"] and "频繁" in body["errorMsg"]


def test_chat_timeout(client, monkeypatch, fake_redis, no_rate_limit):
    class SlowAgent(FakeAgent):
        async def ainvoke(self, messages, config=None, context=None):
            raise TimeoutError

    _patch_chat_deps(monkeypatch, fake_redis, SlowAgent())
    body = client.post("/api/agent/chat", json={"message": "hi"}).json()
    assert not body["success"] and "超时" in body["errorMsg"]


def test_chat_internal_error(client, monkeypatch, fake_redis, no_rate_limit):
    class BadAgent(FakeAgent):
        async def ainvoke(self, messages, config=None, context=None):
            raise RuntimeError("llm boom")

    _patch_chat_deps(monkeypatch, fake_redis, BadAgent())
    body = client.post("/api/agent/chat", json={"message": "hi"}).json()
    assert not body["success"] and "暂时不可用" in body["errorMsg"]


def test_chat_tool_calls_extracted(client, monkeypatch, fake_redis, no_rate_limit):
    messages = [
        AIMessage(content="", tool_calls=[{"name": "get_movie_detail",
                                           "args": {"movie_id": 1},
                                           "id": "call_1", "type": "tool_call"}]),
        ToolMessage(name="get_movie_detail", content=json.dumps(
            {"title": "肖申克的救赎"}, ensure_ascii=False), tool_call_id="1"),
        AIMessage(content="这是最终回复"),
    ]
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent(messages=messages))
    body = client.post("/api/agent/chat", json={"message": "hi"}).json()
    tools = body["data"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "get_movie_detail"
    assert tools[0]["args"] == {"movie_id": 1}
    assert tools[0]["summary"]  # 从 ToolMessage 回填摘要
    assert body["data"]["reply"] == "这是最终回复"


# ---------- /chat/stream SSE ----------


def test_chat_stream_events(client, monkeypatch, fake_redis, no_rate_limit):
    events = [
        ("messages", (AIMessageChunk(content="你"), None)),
        ("messages", (AIMessageChunk(content="好"), None)),
        ("updates", {"node": {"messages": [
            ToolMessage(name="semantic_search",
                        content=json.dumps({"results": [
                            {"type": "movie", "id": 1, "title": "肖申克的救赎", "score": 0.9}]},
                            ensure_ascii=False),
                        tool_call_id="1"),
        ]}}),
    ]
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent(stream_events=events))
    with client.stream("POST", "/api/agent/chat/stream",
                       json={"threadId": THREAD_ID, "message": "hi"}) as resp:
        text = "".join(resp.iter_text())
    assert "event: message" in text
    assert '"delta": "你"' in text and '"delta": "好"' in text
    assert "event: tool" in text and "semantic_search" in text
    assert "event: source" in text and "肖申克的救赎" in text
    assert "event: done" in text and f'"threadId": "{THREAD_ID}"' in text


def test_chat_stream_error(client, monkeypatch, fake_redis, no_rate_limit):
    class BadStreamAgent(FakeAgent):
        async def astream(self, messages, config=None, context=None, stream_mode=None):
            raise RuntimeError("stream boom")
            yield  # pragma: no cover

    _patch_chat_deps(monkeypatch, fake_redis, BadStreamAgent())
    with client.stream("POST", "/api/agent/chat/stream",
                       json={"message": "hi"}) as resp:
        text = "".join(resp.iter_text())
    assert "event: error" in text and "暂时不可用" in text and "stream boom" not in text


def test_chat_rejects_foreign_thread(client, monkeypatch, fake_redis, no_rate_limit):
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent())
    monkeypatch.setattr("app.api.chat.get_session", lambda tid: {"ownerId": "user:2"})
    resp = client.post("/api/agent/chat",
                       json={"threadId": THREAD_ID, "message": "hi"},
                       headers={"authorization": "tok"})
    assert resp.status_code == 403


def test_chat_rejects_unknown_client_thread(client, monkeypatch, fake_redis, no_rate_limit):
    _patch_chat_deps(monkeypatch, fake_redis, FakeAgent())
    monkeypatch.setattr("app.api.chat.get_session", lambda tid: None)
    resp = client.post("/api/agent/chat",
                       json={"threadId": THREAD_ID, "message": "hi"},
                       headers={"authorization": "tok"})
    assert resp.status_code == 404


def test_chat_stream_rate_limited(client, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "chat_rate_limit", 10)
    monkeypatch.setattr("app.api.chat.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.chat.get_redis", lambda: fake_redis)
    fake_redis.counters[f"agent:rate:user:{USER['userId']}"] = 99
    body = client.post("/api/agent/chat/stream", json={"message": "hi"}).json()
    assert not body["success"] and "频繁" in body["errorMsg"]


# ---------- /sessions ----------


def test_sessions_list(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.sessions.list_sessions",
                        lambda uid, cur: ([{"threadId": "a"}], 11))
    body = client.get("/api/agent/sessions", headers={"authorization": "tok"}).json()
    assert body["success"] and body["data"]["list"] == [{"threadId": "a"}]
    assert body["data"]["hasMore"] is True


def test_sessions_guest(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user",
                        lambda token: {"userId": 0, "token": ""})
    body = client.get("/api/agent/sessions").json()
    assert not body["success"] and "登录" in body["errorMsg"]


def test_sessions_delete_ok(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.sessions.get_session",
                        lambda tid: {"ownerId": "user:1"})
    async def delete_checkpoints(tid):
        return None

    monkeypatch.setattr("app.api.sessions.delete_thread_checkpoints", delete_checkpoints)
    monkeypatch.setattr("app.api.sessions.delete_session", lambda *args: None)
    body = client.delete("/api/agent/sessions/t1",
                         headers={"authorization": "tok"}).json()
    assert body["success"]


def test_sessions_delete_not_found(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.sessions.get_session", lambda tid: None)
    body = client.delete("/api/agent/sessions/t1",
                         headers={"authorization": "tok"}).json()
    assert not body["success"] and "不存在" in body["errorMsg"]


def test_sessions_delete_forbidden(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.sessions.get_session",
                        lambda tid: {"ownerId": "user:2"})
    resp = client.delete("/api/agent/sessions/t1", headers={"authorization": "tok"})
    assert resp.status_code == 403


def test_sessions_delete_guest(client, monkeypatch):
    monkeypatch.setattr("app.api.sessions.resolve_user",
                        lambda token: {"userId": 0, "token": ""})
    resp = client.delete("/api/agent/sessions/t1")
    assert resp.status_code == 401


# ---------- /profile ----------


def test_profile_own(client, monkeypatch):
    monkeypatch.setattr("app.api.profile.resolve_user", lambda token: USER)
    monkeypatch.setattr("app.api.profile.extractor.get_or_refresh",
                        lambda uid: {"profileSummary": "喜欢科幻"})
    body = client.get("/api/agent/profile/1",
                      headers={"authorization": "tok"}).json()
    assert body["success"] and body["data"]["profileSummary"] == "喜欢科幻"


def test_profile_forbidden(client, monkeypatch):
    monkeypatch.setattr("app.api.profile.resolve_user", lambda token: USER)
    resp = client.get("/api/agent/profile/2", headers={"authorization": "tok"})
    assert resp.status_code == 403


# ---------- /admin ----------


def test_health(client, monkeypatch, fake_redis):
    monkeypatch.setattr(mysql, "_rows", lambda sql, **kw: [{"x": 1}])
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.admin.es_client.ping", lambda: True)
    monkeypatch.setattr(settings, "deepseek_api_key", "k")
    monkeypatch.setattr(settings, "siliconflow_api_key", "k")
    body = client.get("/api/agent/health").json()
    checks = body["data"]
    assert checks["mysql"] == "ok" and checks["redis"] == "ok"
    assert checks["es"] == "ok" and checks["llm"] == "ok"
    assert checks["embedding"] == "ok"


def test_health_mysql_down(client, monkeypatch, fake_redis):
    monkeypatch.setattr(mysql, "_rows", lambda sql, **kw: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.admin.es_client.ping", lambda: True)
    body = client.get("/api/agent/health").json()
    assert body["data"]["mysql"] == "fail"


def test_admin_endpoint_requires_admin(client, monkeypatch):
    monkeypatch.setattr("app.api.admin.resolve_admin", lambda token: None)
    resp = client.get("/api/agent/health")
    assert resp.status_code == 401


def test_tool_stats(client, monkeypatch, fake_redis):
    from app.services.redis_client import AgentRedisKeys
    fake_redis.zsets[AgentRedisKeys.tool_stats_key()] = {"semantic_search": 3, "draft_review": 1}
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    body = client.get("/api/agent/tool-stats").json()
    stats = body["data"]["stats"]
    assert stats[0]["tool"] == "semantic_search" and stats[0]["count"] == 3
    assert stats[1]["tool"] == "draft_review"


def test_invoke_tool_ok(client, monkeypatch, fake_redis):
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    fake_redis.zsets["movie:hot:"] = {"1": 100}
    monkeypatch.setattr(mysql, "get_movies_by_ids",
                        lambda ids: [{"id": 1, "title": "教父", "rating": 9.1,
                                      "ratingCount": 500, "genre": "剧情", "region": "美国"}])
    monkeypatch.setattr(settings, "admin_tool_invoke_enabled", True)
    body = client.post("/api/agent/tools/list_hot_movies", json={"current": 1}).json()
    assert body["success"] and "教父" in body["data"]["result"]


def test_invoke_tool_unknown(client):
    body = client.post("/api/agent/tools/no_such_tool", json={}).json()
    assert not body["success"] and "不存在" in body["errorMsg"]


def test_invoke_tool_runtime_rejected(client):
    body = client.post("/api/agent/tools/publish_review", json={}).json()
    assert not body["success"] and "不支持直调" in body["errorMsg"]
