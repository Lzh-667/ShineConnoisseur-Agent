"""运维接口：健康检查、ES 同步、工具直调、热门 tool 统计、token 用量。"""

import asyncio
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from app.api.schemas import fail, ok
from app.config.settings import settings
from app.services import es_client, mysql
from app.services.auth import resolve_admin
from app.services.redis_client import AgentRedisKeys, get_redis
from app.tools import TOOLS_BY_NAME

router = APIRouter()


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    admin = resolve_admin(authorization)
    if admin is None:
        raise HTTPException(status_code=401, detail="需要管理员登录")
    return admin


def _usage_view(label: str, data: dict) -> dict:
    """Redis Hash 用量数据 → 视图（含按价格估算的成本）。"""
    input_tokens = int(data.get("inputTokens") or 0)
    output_tokens = int(data.get("outputTokens") or 0)
    cost = (input_tokens * settings.deepseek_input_price
            + output_tokens * settings.deepseek_output_price) / 1_000_000
    return {
        "label": label,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "calls": int(data.get("calls") or 0),
        "estimatedCost": round(cost, 6),
    }


@router.get("/health")
async def health(_: dict = Depends(require_admin)):
    checks = {}

    try:
        mysql._rows("SELECT 1")
        checks["mysql"] = "ok"
    except Exception:
        checks["mysql"] = "fail"

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "fail"

    try:
        checks["es"] = "ok" if es_client.ping() else "fail: ping=false"
    except Exception:
        checks["es"] = "fail"

    checks["llm"] = "ok" if settings.deepseek_api_key else "fail: DEEPSEEK_API_KEY 未配置"
    checks["embedding"] = "ok" if settings.siliconflow_api_key else "fail: SILICONFLOW_API_KEY 未配置"

    return ok(checks)


@router.post("/es/sync")
async def es_sync(type: Literal["all", "movie", "review"] = "all",
                  _: dict = Depends(require_admin)):
    """手动触发 ES 向量索引同步。type: all | movie | review"""
    from app.rag import sync as rag_sync

    result = {}
    if type in ("all", "movie"):
        result["movies"] = await asyncio.to_thread(rag_sync.sync_movies_full)
    if type in ("all", "review"):
        result["reviews"] = await asyncio.to_thread(rag_sync.sync_reviews_incremental)
    return ok(result)


@router.get("/tool-stats")
async def tool_stats(month: Annotated[str | None, Query(pattern=r"^\d{6}$")] = None,
                     _: dict = Depends(require_admin)):
    """热门 tool 调用排行（Redis ZSet，月维度，默认当月）。month 格式 YYYYMM。"""
    key = AgentRedisKeys.tool_stats_key(month) if month else AgentRedisKeys.tool_stats_key()
    items = get_redis().zrevrange(key, 0, 19, withscores=True)
    return ok({
        "month": month or datetime.now().strftime("%Y%m"),
        "stats": [{"tool": name, "count": int(score)} for name, score in items],
    })


@router.get("/usage/session/{thread_id}")
async def usage_session(thread_id: str, _: dict = Depends(require_admin)):
    """单会话 token 用量（含估算成本）。"""
    data = get_redis().hgetall(AgentRedisKeys.USAGE_SESSION.format(thread_id))
    if not data:
        return fail("该会话暂无 token 用量数据")
    return ok(_usage_view(thread_id, data))


@router.get("/usage/daily")
async def usage_daily(days: Annotated[int, Query(ge=1, le=31)] = 7,
                      _: dict = Depends(require_admin)):
    """最近 N 天全站 token 用量（含估算成本）。"""
    r = get_redis()
    items = []
    for i in range(days):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        data = r.hgetall(AgentRedisKeys.USAGE_DAILY.format(day))
        if data:
            items.append(_usage_view(day, data))
    return ok({"days": items})


@router.post("/tools/{tool_name}")
async def invoke_tool(tool_name: str, body: dict = Body(default={}),
                      _: dict = Depends(require_admin)):
    """直接调用某个 agent 工具（调试/前端快捷能力）。"""
    tool = TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return fail(f"工具 {tool_name} 不存在")
    if "runtime" in (tool.args_schema.model_fields or {}):
        return fail("该工具需要运行期上下文，不支持直调")
    if not settings.admin_tool_invoke_enabled:
        return fail("工具直调已禁用；仅可在受控调试环境开启")
    try:
        result = await asyncio.to_thread(tool.invoke, body)
        return ok({"result": result})
    except Exception:
        return fail("工具调用失败，请查看服务日志")
