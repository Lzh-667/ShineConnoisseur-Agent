"""Checkpointer 工厂：sqlite（默认，崩溃可恢复）/ memory（开发调试）。"""

from functools import lru_cache
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config.settings import settings


@lru_cache
def create_checkpointer() -> BaseCheckpointSaver:
    if settings.agent_checkpoint == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()



    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = aiosqlite.connect(str(db_path))
    return AsyncSqliteSaver(conn)


async def delete_thread_checkpoints(thread_id: str) -> None:
    """删除会话时连同 LangGraph 历史删除，避免元数据删除后的隐私残留。"""
    saver = create_checkpointer()
    delete = getattr(saver, "adelete_thread", None)
    if delete is not None:
        await delete(thread_id)


async def close_checkpointer() -> None:
    """关闭 SQLite 连接，避免 Uvicorn 重载或退出时遗留连接。"""
    saver = create_checkpointer()
    conn = getattr(saver, "conn", None)
    if conn is not None:
        await conn.close()
    create_checkpointer.cache_clear()
