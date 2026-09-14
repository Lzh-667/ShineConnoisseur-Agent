"""token 用量统计：UsageTrackingMiddleware + /usage 接口测试。"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.agent.context import AgentContext
from app.agent.middleware import UsageTrackingMiddleware
from app.services.redis_client import AgentRedisKeys


def _state_with_usage(input_tokens: int, output_tokens: int) -> dict:
    msg = AIMessage(content="回复",
                    usage_metadata={"input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "total_tokens": input_tokens + output_tokens})
    return {"messages": [msg]}


def test_usage_middleware_records_session_and_daily(monkeypatch, fake_redis):
    monkeypatch.setattr("app.agent.middleware.get_redis", lambda: fake_redis)
    mw = UsageTrackingMiddleware()
    ctx = AgentContext(user_id=1, thread_id="t1")
    runtime = SimpleNamespace(context=ctx)
    state = _state_with_usage(100, 50)
    asyncio.run(mw.aafter_model(state, runtime))

    session = fake_redis.hgetall(AgentRedisKeys.USAGE_SESSION.format("t1"))
    assert session["inputTokens"] == "100"
    assert session["outputTokens"] == "50"
    assert session["calls"] == "1"

    from datetime import datetime
    daily_key = AgentRedisKeys.USAGE_DAILY.format(datetime.now().strftime("%Y%m%d"))
    assert fake_redis.hgetall(daily_key)["inputTokens"] == "100"


def test_usage_middleware_accumulates(monkeypatch, fake_redis):
    monkeypatch.setattr("app.agent.middleware.get_redis", lambda: fake_redis)
    mw = UsageTrackingMiddleware()
    runtime = SimpleNamespace(context=AgentContext(thread_id="t1"))
    for _ in range(2):
        asyncio.run(mw.aafter_model(_state_with_usage(10, 20), runtime))
    session = fake_redis.hgetall(AgentRedisKeys.USAGE_SESSION.format("t1"))
    assert session["inputTokens"] == "20" and session["calls"] == "2"


def test_usage_middleware_skips_empty(monkeypatch, fake_redis):
    monkeypatch.setattr("app.agent.middleware.get_redis", lambda: fake_redis)
    mw = UsageTrackingMiddleware()
    runtime = SimpleNamespace(context=AgentContext(thread_id="t1"))
    asyncio.run(mw.aafter_model({"messages": [AIMessage(content="无usage")]}, runtime))
    assert not fake_redis.hashes  # 无 usage_metadata 不落任何数据


def test_usage_middleware_guards_bad_redis(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.agent.middleware.get_redis", boom)
    mw = UsageTrackingMiddleware()
    runtime = SimpleNamespace(context=AgentContext(thread_id="t1"))
    asyncio.run(mw.aafter_model(_state_with_usage(1, 1), runtime))  # 不抛异常


def test_usage_session_api(client, monkeypatch, fake_redis):
    fake_redis.hset(AgentRedisKeys.USAGE_SESSION.format("t1"),
                    {"inputTokens": 1000, "outputTokens": 500, "calls": 3})
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.api.admin.settings.deepseek_input_price", 2.0)
    monkeypatch.setattr("app.api.admin.settings.deepseek_output_price", 8.0)
    body = client.get("/api/agent/usage/session/t1").json()
    data = body["data"]
    assert data["inputTokens"] == 1000 and data["calls"] == 3
    assert data["estimatedCost"] == round((1000 * 2.0 + 500 * 8.0) / 1_000_000, 6)


def test_usage_session_api_empty(client, monkeypatch, fake_redis):
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    body = client.get("/api/agent/usage/session/nope").json()
    assert not body["success"] and "暂无" in body["errorMsg"]


def test_usage_daily_api(client, monkeypatch, fake_redis):
    from datetime import datetime
    day = datetime.now().strftime("%Y%m%d")
    fake_redis.hset(AgentRedisKeys.USAGE_DAILY.format(day),
                    {"inputTokens": 100, "outputTokens": 200, "calls": 2})
    monkeypatch.setattr("app.api.admin.get_redis", lambda: fake_redis)
    body = client.get("/api/agent/usage/daily?days=7").json()
    days = body["data"]["days"]
    assert len(days) == 1 and days[0]["label"] == day
    assert days[0]["calls"] == 2
