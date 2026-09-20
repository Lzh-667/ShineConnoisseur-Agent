"""ES 向量索引数据同步。

- 电影：启动全量 + 每日一次（60 条规模）
- 影评：增量轮询（5 分钟），游标 agent:sync:review:cursor 存 Redis；
  后端发布/删除影评后 5 分钟内进入/移出 review_vec
"""

import asyncio
import json
import logging
import time
from contextlib import contextmanager

from app.rag import es_hybrid
from app.rag.es_hybrid import REVIEW_VEC_INDEX
from app.services import mysql
from app.services.es_client import MOVIE_VEC_INDEX
from app.services.redis_client import AgentRedisKeys, get_redis

logger = logging.getLogger(__name__)

REVIEW_POLL_SECONDS = 5 * 60
MOVIE_RESYNC_SECONDS = 24 * 3600
SYNC_BATCH_SIZE = 100
SYNC_LOCK_SECONDS = 15 * 60


def _decode_cursor(raw: str | None) -> tuple[str, int] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return str(data["updateTime"]), int(data["id"])
    except (ValueError, TypeError, KeyError):
        # 兼容旧版本只存时间戳的 cursor；从该时间的第一个 id 继续读取。
        return raw, 0


def _encode_cursor(cursor: tuple[str, int]) -> str:
    return json.dumps({"updateTime": cursor[0], "id": cursor[1]})


@contextmanager
def _sync_lock(name: str):
    """多实例时只允许一个同步器推进同一类游标。"""
    lock = get_redis().lock(
        AgentRedisKeys.SYNC_LOCK.format(name), timeout=SYNC_LOCK_SECONDS,
        blocking_timeout=0, thread_local=False,
    )
    if not lock.acquire(blocking=False):
        yield False
        return
    try:
        yield True
    finally:
        try:
            if lock.owned():
                lock.release()
        except Exception:
            logger.warning("sync lock release failed: %s", name, exc_info=True)


def sync_movies_full() -> dict:
    """全量同步电影：status=1 写入向量索引，其余清理。"""
    with _sync_lock("movies") as acquired:
        if not acquired:
            return {"skipped": "another sync is running"}
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
    with _sync_lock("reviews") as acquired:
        if not acquired:
            return {"skipped": "another sync is running"}
        r = get_redis()
        cursor = _decode_cursor(r.get(AgentRedisKeys.SYNC_REVIEW_CURSOR))
        indexed_total = deleted_total = 0
        while True:
            reviews = mysql.get_reviews_updated_after(cursor, limit=SYNC_BATCH_SIZE)
            if not reviews:
                return {"synced": indexed_total, "deleted": deleted_total, "cursor": cursor}

            active = [x for x in reviews if x.get("status") == 1]
            inactive_ids = [x["id"] for x in reviews if x.get("status") != 1]
            indexed_total += es_hybrid.index_reviews(active)
            if inactive_ids:
                es_hybrid.delete_docs(REVIEW_VEC_INDEX, inactive_ids)
                deleted_total += len(inactive_ids)

            last = reviews[-1]
            if not last.get("update_time"):
                raise RuntimeError(f"review {last['id']} missing update_time")
            cursor = (str(last["update_time"]), int(last["id"]))
            r.set(AgentRedisKeys.SYNC_REVIEW_CURSOR, _encode_cursor(cursor))
            if len(reviews) < SYNC_BATCH_SIZE:
                return {"synced": indexed_total, "deleted": deleted_total, "cursor": cursor}


def sync_reviews_full() -> dict:
    """重置游标并全量同步（手动触发/调试用）。"""
    get_redis().delete(AgentRedisKeys.SYNC_REVIEW_CURSOR)
    return sync_reviews_incremental()


async def _safe(fn, name: str) -> bool:
    try:
        result = await asyncio.to_thread(fn)
        logger.info("sync %s done: %s", name, result)
        return "skipped" not in result
    except Exception:
        logger.exception("sync %s failed", name)
        return False


async def run_sync_loop() -> None:
    """后台同步任务：启动即同步电影+影评，此后影评每 5 分钟轮询、电影每日重同步。"""
    last_movie_sync = 0.0
    while True:
        ready = await _safe(es_hybrid.ensure_indices, "ensure_indices")
        movie_due = ready and time.time() - last_movie_sync > MOVIE_RESYNC_SECONDS
        movie_synced = await _safe(sync_movies_full, "movies") if movie_due else False
        if movie_synced:
            last_movie_sync = time.time()
        if ready:
            await _safe(sync_reviews_incremental, "reviews")
        await asyncio.sleep(REVIEW_POLL_SECONDS)
