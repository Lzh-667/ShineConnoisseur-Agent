"""FastAPI 入口：光影鉴赏家 AI Agent 服务（端口 8001）。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat, sessions
from app.services import es_client, mysql
from app.services.redis_client import close_redis, get_redis

app = FastAPI(title="ShineConnoisseur Agent", version="0.1.0")

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


@app.on_event("startup")
async def startup():
    # 预热连接
    mysql.get_engine()
    get_redis()


@app.on_event("shutdown")
async def shutdown():
    close_redis()
    es_client.close_es()
