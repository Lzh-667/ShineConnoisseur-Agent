"""Checkpointer 工厂：sqlite（默认，崩溃可恢复）/ memory（开发调试）。"""

from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.config.settings import settings


def create_checkpointer() -> BaseCheckpointSaver:
    if settings.agent_checkpoint == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    import aiosqlite

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = aiosqlite.connect(str(db_path))
    return AsyncSqliteSaver(conn)
