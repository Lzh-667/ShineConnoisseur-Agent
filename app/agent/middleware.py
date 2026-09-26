"""自定义中间件：热门 tool 统计、用户画像注入、token 用量统计。

注意：agent 通过 ainvoke/astream 异步调用，钩子必须同时实现 async 版本。
"""

import asyncio
import json
import logging
import time
from datetime import datetime

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import SystemMessage

from app.memory import extractor
from app.observability.metrics import LLM_TOKENS, TOOL_CALLS, TOOL_DURATION
from app.services.redis_client import AgentRedisKeys, get_redis

logger = logging.getLogger(__name__)

PROFILE_MARKER = "## 当前用户画像"
PAGE_CONTEXT_MARKER = "## 当前页面上下文"


class ToolUsageMiddleware(AgentMiddleware):
    """统计每个 tool 的调用次数（Redis ZSet，月维度），用于热门 tool 排行。"""

    def _count(self, request: ToolCallRequest) -> None:
        try:
            name = request.tool_call.get("name", "unknown")
            get_redis().zincrby(AgentRedisKeys.tool_stats_key(), 1, name)
        except Exception:
            logger.warning("tool 统计失败", exc_info=True)

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        self._count(request)
        name = request.tool_call.get("name", "unknown")
        started = time.perf_counter()
        status = "error"
        try:
            result = handler(request)
            status = "success"
            return result
        finally:
            TOOL_CALLS.labels(name, status).inc()
            TOOL_DURATION.labels(name).observe(time.perf_counter() - started)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        await asyncio.to_thread(self._count, request)
        name = request.tool_call.get("name", "unknown")
        started = time.perf_counter()
        status = "error"
        try:
            result = await handler(request)
            status = "success"
            return result
        finally:
            TOOL_CALLS.labels(name, status).inc()
            TOOL_DURATION.labels(name).observe(time.perf_counter() - started)


class ProfileInjectionMiddleware(AgentMiddleware):
    """每轮模型调用前，把用户画像摘要注入 system 消息（幂等，带标记防重复）。"""

    def _inject(self, state, runtime) -> None:
        try:
            ctx = runtime.context
            if ctx is None:
                return
            additions = []
            if getattr(ctx, "user_id", 0):
                profile = extractor.get_or_refresh(ctx.user_id)
                summary = profile.get("profileSummary") or ""
                if summary:
                    additions.append(
                        f"{PROFILE_MARKER}\n{summary}\n"
                        "（个性化推荐时可结合用户偏好，但不要在回复中复述或炫耀画像内容）")
            if getattr(ctx, "page_context", None):
                raw_context = json.dumps(ctx.page_context, ensure_ascii=False, default=str)
                additions.append(f"{PAGE_CONTEXT_MARKER}\n{raw_context[:1000]}")
            if not additions:
                return
            messages = state["messages"]
            if messages and isinstance(messages[0], SystemMessage):
                base = messages[0].content
                additions = [
                    addition for addition in additions
                    if not (addition.startswith(PROFILE_MARKER) and PROFILE_MARKER in base)
                    and not (addition.startswith(PAGE_CONTEXT_MARKER) and PAGE_CONTEXT_MARKER in base)
                ]
                if not additions:
                    return
                messages[0] = SystemMessage(content=f"{base}\n\n" + "\n\n".join(additions))
            else:
                messages.insert(0, SystemMessage(content="\n\n".join(additions)))
        except Exception:
            logger.warning("画像注入失败", exc_info=True)

    def before_model(self, state, runtime):
        self._inject(state, runtime)

    async def abefore_model(self, state, runtime):
        await asyncio.to_thread(self._inject, state, runtime)


class UsageTrackingMiddleware(AgentMiddleware):
    """每轮模型调用后累计 token 用量（会话/日维度），支撑成本统计。

    DeepSeek 在 usage_metadata 中返回 input_tokens/output_tokens，
    流式时 langchain-openai 默认开启 stream_usage，聚合后的 AIMessage 同样携带。
    """

    def _record(self, state, runtime) -> None:
        try:
            messages = state.get("messages", [])
            if not messages:
                return
            usage = getattr(messages[-1], "usage_metadata", None) or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            if input_tokens == 0 and output_tokens == 0:
                return
            LLM_TOKENS.labels("input").inc(input_tokens)
            LLM_TOKENS.labels("output").inc(output_tokens)
            ctx = runtime.context
            r = get_redis()
            if ctx is not None and getattr(ctx, "thread_id", ""):
                key = AgentRedisKeys.USAGE_SESSION.format(ctx.thread_id)
                r.hincrby(key, "inputTokens", input_tokens)
                r.hincrby(key, "outputTokens", output_tokens)
                r.hincrby(key, "calls", 1)
                r.expire(key, AgentRedisKeys.USAGE_SESSION_TTL)
            daily = AgentRedisKeys.USAGE_DAILY.format(datetime.now().strftime("%Y%m%d"))
            r.hincrby(daily, "inputTokens", input_tokens)
            r.hincrby(daily, "outputTokens", output_tokens)
            r.hincrby(daily, "calls", 1)
            r.expire(daily, AgentRedisKeys.USAGE_DAILY_TTL)
        except Exception:
            logger.warning("token 用量统计失败", exc_info=True)

    def after_model(self, state, runtime):
        self._record(state, runtime)

    async def aafter_model(self, state, runtime):
        await asyncio.to_thread(self._record, state, runtime)
