"""对话接口：POST /api/agent/chat（非流式）、POST /api/agent/chat/stream（SSE）。"""

import asyncio
import json
import logging
import secrets
import time
import uuid

from fastapi import APIRouter, Cookie, Header, HTTPException, Response
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.builder import get_agent
from app.agent.context import AgentContext
from app.api.schemas import ChatData, ChatRequest, ToolCallInfo, fail, ok
from app.config.settings import settings
from app.services.auth import resolve_user
from app.services.redis_client import AgentRedisKeys, get_redis
from app.services.session_store import get_session, touch_session

router = APIRouter()
logger = logging.getLogger(__name__)


_RATE_LIMIT_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return 1
"""


def _rate_limited(subject: str) -> bool:
    """Redis Lua 原子滑动窗口限流，避免窗口边界突发和 INCR/EXPIRE 竞态。"""
    r = get_redis()
    key = AgentRedisKeys.RATE.format(subject)
    now_ms = int(time.time() * 1000)
    allowed = r.eval(
        _RATE_LIMIT_SCRIPT, 1, key, now_ms,
        AgentRedisKeys.RATE_WINDOW_SECONDS * 1000,
        settings.chat_rate_limit, secrets.token_hex(8),
    )
    return not bool(allowed)


def _extract_tools(messages: list) -> list[ToolCallInfo]:
    tools: list[ToolCallInfo] = []
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tools.append(ToolCallInfo(name=tc.get("name", ""), args=tc.get("args")))
        elif isinstance(m, ToolMessage):
            for t in reversed(tools):
                if t.summary is None:
                    content = m.content if isinstance(m.content, str) else str(m.content)
                    t.summary = content[:120]
                    break
    return tools


def _new_thread_id() -> str:
    return uuid.uuid4().hex


def _session_owner(user: dict, guest_id: str | None) -> tuple[str, str | None]:
    if user["userId"]:
        return f"user:{user['userId']}", None
    # 未登录用户通过 HttpOnly cookie 获得隔离的会话身份，不能再共享 ownerId=0。
    if not guest_id:
        guest_id = secrets.token_urlsafe(24)
    return f"guest:{guest_id}", guest_id


async def _prepare_session(req: ChatRequest, user: dict,
                           guest_id: str | None) -> tuple[str, str, str | None]:
    owner_id, new_guest_id = _session_owner(user, guest_id)
    if req.threadId:
        meta = await asyncio.to_thread(get_session, req.threadId)
        if not meta:
            # 新会话只能由服务端生成 ID，防止复用已删除/未知 checkpoint。
            raise HTTPException(status_code=404, detail="会话不存在，请新建对话")
        if meta.get("ownerId") != owner_id:
            raise HTTPException(status_code=403, detail="无权访问该会话")
        thread_id = req.threadId
    else:
        thread_id = _new_thread_id()
    await asyncio.to_thread(touch_session, thread_id, owner_id, req.message)
    return thread_id, owner_id, new_guest_id


def _set_guest_cookie(response: Response, guest_id: str | None) -> None:
    if guest_id:
        response.set_cookie(
            key="agent_guest_id", value=guest_id, max_age=7 * 24 * 3600,
            httponly=True, samesite="lax", secure=settings.agent_cookie_secure,
        )


def _semantic_sources(content: str):
    """从 semantic_search 工具结果中解析引用来源，发 SSE source 事件。"""
    try:
        data = json.loads(content)
        for item in data.get("results", []):
            yield {"event": "source",
                   "data": json.dumps(
                       {"type": item.get("type", "movie"), "id": item.get("id"),
                        "title": item.get("title", ""),
                        "score": item.get("score")}, ensure_ascii=False)}
    except (json.JSONDecodeError, AttributeError):
        return


@router.post("/chat")
async def chat(req: ChatRequest, response: Response,
               authorization: str | None = Header(default=None),
               agent_guest_id: str | None = Cookie(default=None)):
    user = await asyncio.to_thread(resolve_user, authorization)
    owner_id, _ = _session_owner(user, agent_guest_id)
    if await asyncio.to_thread(_rate_limited, owner_id):
        return fail("发言太频繁了，请稍等一分钟再试")
    thread_id, _, new_guest_id = await _prepare_session(req, user, agent_guest_id)
    _set_guest_cookie(response, new_guest_id)

    agent = get_agent()
    ctx = AgentContext(user_id=user["userId"], thread_id=thread_id, token=user["token"],
                       page_context=req.extra or {})
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": req.message}]},
                config={"configurable": {"thread_id": thread_id}},
                context=ctx,
            ),
            timeout=300,
        )
    except TimeoutError:
        return fail("AI 响应超时，请稍后重试")
    except Exception:
        logger.exception("chat invocation failed, thread_id=%s", thread_id)
        return fail("AI 服务暂时不可用，请稍后重试")

    messages = result.get("messages", [])
    reply = messages[-1].content if messages else ""
    data = ChatData(
        threadId=thread_id,
        reply=reply if isinstance(reply, str) else str(reply),
        tools=_extract_tools(messages),
    )
    return ok(data.model_dump())


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, authorization: str | None = Header(default=None),
                      agent_guest_id: str | None = Cookie(default=None)):
    user = await asyncio.to_thread(resolve_user, authorization)
    owner_id, _ = _session_owner(user, agent_guest_id)
    if await asyncio.to_thread(_rate_limited, owner_id):
        return fail("发言太频繁了，请稍等一分钟再试")
    thread_id, _, new_guest_id = await _prepare_session(req, user, agent_guest_id)

    agent = get_agent()
    ctx = AgentContext(user_id=user["userId"], thread_id=thread_id, token=user["token"],
                       page_context=req.extra or {})
    config = {"configurable": {"thread_id": thread_id}}

    async def gen():
        start = time.time()
        try:
            async for mode, chunk in agent.astream(
                {"messages": [{"role": "user", "content": req.message}]},
                config=config,
                context=ctx,
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    msg, _meta = chunk
                    if isinstance(msg, AIMessageChunk) and msg.content:
                        yield {"event": "message",
                               "data": json.dumps({"delta": msg.content}, ensure_ascii=False)}
                elif mode == "updates":
                    for update in chunk.values():
                        # __start__ 等伪节点的 update 可能为 None
                        msgs = update.get("messages", []) if isinstance(update, dict) else []
                        for m in msgs:
                            if isinstance(m, ToolMessage):
                                content = m.content if isinstance(m.content, str) else str(m.content)
                                yield {"event": "tool",
                                       "data": json.dumps(
                                           {"name": m.name, "status": "end",
                                            "summary": content[:120]}, ensure_ascii=False)}
                                if m.name == "semantic_search":
                                    for s in _semantic_sources(content):
                                        yield s
            yield {"event": "done",
                   "data": json.dumps({"threadId": thread_id,
                                       "durationMs": int((time.time() - start) * 1000)})}
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("streaming chat failed, thread_id=%s", thread_id)
            yield {"event": "error",
                   "data": json.dumps({"message": "AI 服务暂时不可用，请稍后重试"}, ensure_ascii=False)}

    response = EventSourceResponse(gen(), ping=15)
    _set_guest_cookie(response, new_guest_id)
    return response
