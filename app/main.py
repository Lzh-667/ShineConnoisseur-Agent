"""FastAPI 入口：光影鉴赏家 AI Agent 服务（端口 8001）。"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

from app.api import admin, chat, profile, sessions
from app.observability.metrics import HTTP_DURATION, HTTP_REQUESTS, metrics_app
from app.rag import sync as rag_sync
from app.services import es_client, mysql
from app.services.redis_client import close_redis, get_redis

_sync_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.agent.checkpointer import close_checkpointer
    from app.config.settings import settings

    settings.validate_runtime_config()
    # 预热连接
    mysql.get_engine()
    get_redis()
    # 长期记忆表（幂等建表）
    from app.memory.store import ensure_tables

    ensure_tables()
    # ES 向量索引确保存在 + 初始同步 + 增量轮询（后台任务，不阻塞启动）
    global _sync_task
    _sync_task = asyncio.create_task(rag_sync.run_sync_loop())
    yield
    if _sync_task:
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
    await close_checkpointer()
    close_redis()
    es_client.close_es()


app = FastAPI(title="ShineConnoisseur Agent", version="0.3.0", lifespan=lifespan)


@app.middleware("http")
async def observe_http(request, call_next):
    """记录低基数 HTTP 指标；动态参数使用路由模板而不是原始 URL。"""
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
        HTTP_DURATION.labels(request.method, route).observe(time.perf_counter() - started)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["authorization"],
)

app.include_router(admin.router, prefix="/api/agent", tags=["admin"])
app.include_router(chat.router, prefix="/api/agent", tags=["chat"])
app.include_router(sessions.router, prefix="/api/agent", tags=["sessions"])
app.include_router(profile.router, prefix="/api/agent", tags=["profile"])
app.mount("/metrics", metrics_app())
