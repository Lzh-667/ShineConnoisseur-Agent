"""运维接口：健康检查、ES 同步、工具直调、热门 tool 统计。"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Body

from app.api.schemas import fail, ok
from app.config.settings import settings
from app.services import es_client, mysql
from app.services.redis_client import AgentRedisKeys, get_redis
from app.tools import TOOLS_BY_NAME

router = APIRouter()


@router.get("/health")
async def health():
    checks = {}

    try:
        mysql._rows("SELECT 1")
        checks["mysql"] = "ok"
    except Exception as e:
        checks["mysql"] = f"fail: {e}"

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"fail: {e}"

    try:
        checks["es"] = "ok" if es_client.ping() else "fail: ping=false"
    except Exception as e:
        checks["es"] = f"fail: {e}"

    checks["llm"] = "ok" if settings.deepseek_api_key else "fail: DEEPSEEK_API_KEY 未配置"
    checks["embedding"] = "ok" if settings.siliconflow_api_key else "fail: SILICONFLOW_API_KEY 未配置"

    return ok(checks)


@router.post("/es/sync")
async def es_sync(type: str = "all"):
    """手动触发 ES 向量索引同步。type: all | movie | review"""
    from app.rag import sync as rag_sync

    result = {}
    if type in ("all", "movie"):
        result["movies"] = await asyncio.to_thread(rag_sync.sync_movies_full)
    if type in ("all", "review"):
        result["reviews"] = await asyncio.to_thread(rag_sync.sync_reviews_incremental)
    if not result:
        return fail(f"未知 type: {type}，可选 all/movie/review")
    return ok(result)


@router.get("/tool-stats")
async def tool_stats(month: str | None = None):
    """热门 tool 调用排行（Redis ZSet，月维度，默认当月）。month 格式 YYYYMM。"""
    key = AgentRedisKeys.tool_stats_key(month) if month else AgentRedisKeys.tool_stats_key()
    items = get_redis().zrevrange(key, 0, 19, withscores=True)
    return ok({
        "month": month or datetime.now().strftime("%Y%m"),
        "stats": [{"tool": name, "count": int(score)} for name, score in items],
    })


@router.post("/tools/{tool_name}")
async def invoke_tool(tool_name: str, body: dict = Body(default={})):
    """直接调用某个 agent 工具（调试/前端快捷能力）。"""
    tool = TOOLS_BY_NAME.get(tool_name)
    if tool is None:
        return fail(f"工具 {tool_name} 不存在")
    if "runtime" in (tool.args_schema.model_fields or {}):
        return fail("该工具需要运行期上下文，不支持直调")
    try:
        result = await asyncio.to_thread(tool.invoke, body)
        return ok({"result": result})
    except Exception as e:
        return fail(str(e))
