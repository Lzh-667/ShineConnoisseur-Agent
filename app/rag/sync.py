"""ES 向量索引数据同步。

- 电影：启动全量 + 每日一次（60 条规模）
- 影评：增量轮询（5 分钟），游标 agent:sync:review:cursor 存 Redis；
  后端发布/删除影评后 5 分钟内进入/移出 review_vec
"""

import asyncio
import logging
import time
from datetime import datetime

from app.rag import es_hybrid
from app.rag.es_hybrid import REVIEW_VEC_INDEX
from app.services import mysql
from app.services.es_client import MOVIE_VEC_INDEX
from app.services.redis_client import AgentRedisKeys, get_redis

logger = logging.getLogger(__name__)

REVIEW_POLL_SECONDS = 5 * 60
MOVIE_RESYNC_SECONDS = 24 * 3600


def sync_movies_full() -> dict:
    """全量同步电影：status=1 写入向量索引，其余清理。"""
    movies = mysql.get_all_movies_for_sync()
    active = [m for m in movies if m.get("status") == 1]
    indexed = es_hybrid.index_movies(active)
    current_ids = es_hybrid.list_index_ids(MOVIE_VEC_INDEX)
    active_ids = {m["id"] for m in active}
    stale = current_ids - active_ids
    if stale:
        es_hybrid.delete_docs(MOVIE_VEC_INDEX, list(stale))
    return {"indexed": indexed, "deleted": len(stale), "total_active": len(active)}


def sync_reviews_incremental() -> dict:
    """增量同步影评；游标缺失时先全量。失败不推进游标（下次轮询重试）。"""
    r = get_redis()
    cursor = r.get(AgentRedisKeys.SYNC_REVIEW_CURSOR)
    reviews = mysql.get_reviews_updated_after(cursor)
    if not reviews:
        return {"synced": 0, "deleted": 0, "cursor": cursor}

    active = [x for x in reviews if x.get("status") == 1]
    inactive_ids = [x["id"] for x in reviews if x.get("status") != 1]

    indexed = es_hybrid.index_reviews(active)
    if inactive_ids:
        es_hybrid.delete_docs(REVIEW_VEC_INDEX, inactive_ids)

    new_cursor = max(str(x["update_time"]) for x in reviews
                     if x.get("update_time")) or cursor
    r.set(AgentRedisKeys.SYNC_REVIEW_CURSOR, new_cursor)
    return {"synced": indexed, "deleted": len(inactive_ids), "cursor": new_cursor}


def sync_reviews_full() -> dict:
    """重置游标并全量同步（手动触发/调试用）。"""
    get_redis().delete(AgentRedisKeys.SYNC_REVIEW_CURSOR)
    return sync_reviews_incremental()


async def _safe(fn, name: str) -> None:
    try:
        result = await asyncio.to_thread(fn)
        logger.info("sync %s done: %s", name, result)
    except Exception:
        logger.exception("sync %s failed", name)


async def run_sync_loop() -> None:
    """后台同步任务：启动即同步电影+影评，此后影评每 5 分钟轮询、电影每日重同步。"""
    await _safe(es_hybrid.ensure_indices, "ensure_indices")
    await _safe(sync_movies_full, "movies")
    await _safe(sync_reviews_incremental, "reviews")

    last_movie_sync = time.time()
    while True:
        await asyncio.sleep(REVIEW_POLL_SECONDS)
        await _safe(sync_reviews_incremental, "reviews")
        if time.time() - last_movie_sync > MOVIE_RESYNC_SECONDS:
            await _safe(sync_movies_full, "movies")
            last_movie_sync = time.time()
