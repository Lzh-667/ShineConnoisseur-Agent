"""自定义中间件：热门 tool 统计、用户画像注入。

注意：agent 通过 ainvoke/astream 异步调用，钩子必须同时实现 async 版本。
"""

import logging

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import SystemMessage

from app.memory import extractor
from app.services.redis_client import AgentRedisKeys, get_redis

logger = logging.getLogger(__name__)

PROFILE_MARKER = "## 当前用户画像"


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
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        self._count(request)
        return await handler(request)


class ProfileInjectionMiddleware(AgentMiddleware):
    """每轮模型调用前，把用户画像摘要注入 system 消息（幂等，带标记防重复）。"""

    def _inject(self, state, runtime) -> None:
        try:
            ctx = runtime.context
            if ctx is None or getattr(ctx, "user_id", 0) == 0:
                return
            profile = extractor.get_or_refresh(ctx.user_id)
            summary = profile.get("profileSummary") or ""
            if not summary:
                return
            messages = state["messages"]
            if not messages or not isinstance(messages[0], SystemMessage):
                return
            base = messages[0].content
            if PROFILE_MARKER in base:
                return
            messages[0] = SystemMessage(content=(
                f"{base}\n\n{PROFILE_MARKER}\n{summary}\n"
                "（个性化推荐时可结合用户偏好，但不要在回复中复述或炫耀画像内容）"))
        except Exception:
            logger.warning("画像注入失败", exc_info=True)

    def before_model(self, state, runtime):
        self._inject(state, runtime)
        return None

    async def abefore_model(self, state, runtime):
        self._inject(state, runtime)
        return None
