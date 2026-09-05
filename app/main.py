"""FastAPI 入口：光影鉴赏家 AI Agent 服务（端口 8001）。"""

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

from app.api import admin, chat, profile, sessions
from app.rag import sync as rag_sync
from app.services import es_client, mysql
from app.services.redis_client import close_redis, get_redis

app = FastAPI(title="ShineConnoisseur Agent", version="0.3.0")

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

_sync_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    # 预热连接
    mysql.get_engine()
    get_redis()
    # 长期记忆表（幂等建表）
    from app.memory.store import ensure_tables

    ensure_tables()
    # ES 向量索引确保存在 + 初始同步 + 增量轮询（后台任务，不阻塞启动）
    global _sync_task
    _sync_task = asyncio.create_task(rag_sync.run_sync_loop())


@app.on_event("shutdown")
async def shutdown():
    global _sync_task
    if _sync_task:
        _sync_task.cancel()
    close_redis()
    es_client.close_es()
