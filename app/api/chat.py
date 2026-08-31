"""对话接口：POST /api/agent/chat（非流式）、POST /api/agent/chat/stream（SSE）。"""

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Header
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.builder import get_agent
from app.agent.context import AgentContext
from app.api.schemas import ChatData, ChatRequest, ToolCallInfo, fail, ok
from app.services.auth import resolve_user
from app.services.session_store import touch_session

router = APIRouter()


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


@router.post("/chat")
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    user = resolve_user(authorization)
    thread_id = req.threadId or _new_thread_id()
    touch_session(thread_id, user["userId"], req.message)

    agent = get_agent()
    ctx = AgentContext(user_id=user["userId"], thread_id=thread_id)
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": req.message}]},
                config={"configurable": {"thread_id": thread_id}},
                context=ctx,
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        return fail("AI 响应超时，请稍后重试")
    except Exception as e:
        return fail(f"AI 服务异常：{e}")

    messages = result.get("messages", [])
    reply = messages[-1].content if messages else ""
    data = ChatData(
        threadId=thread_id,
        reply=reply if isinstance(reply, str) else str(reply),
        tools=_extract_tools(messages),
    )
    return ok(data.model_dump())


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, authorization: str | None = Header(default=None)):
    user = resolve_user(authorization)
    thread_id = req.threadId or _new_thread_id()
    touch_session(thread_id, user["userId"], req.message)

    agent = get_agent()
    ctx = AgentContext(user_id=user["userId"], thread_id=thread_id)
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
                    for _node, update in chunk.items():
                        msgs = update.get("messages", [])
                        for m in msgs:
                            if isinstance(m, ToolMessage):
                                content = m.content if isinstance(m.content, str) else str(m.content)
                                yield {"event": "tool",
                                       "data": json.dumps(
                                           {"name": m.name, "status": "end",
                                            "summary": content[:120]}, ensure_ascii=False)}
            yield {"event": "done",
                   "data": json.dumps({"threadId": thread_id,
                                       "durationMs": int((time.time() - start) * 1000)})}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)
