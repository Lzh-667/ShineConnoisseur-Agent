"""会话元信息存储（Redis Hash agent:session:meta:{threadId}）。"""

import time

from app.services.redis_client import AgentRedisKeys, get_redis


def touch_session(thread_id: str, owner_id: str, message: str) -> None:
    """新建或续期会话元信息；新会话用首条消息生成标题。"""
    r = get_redis()
    key = AgentRedisKeys.SESSION_META.format(thread_id)
    now = int(time.time())
    if not r.exists(key):
        title = message.strip().replace("\n", " ")[:20] or "新对话"
        r.hset(key, mapping={
            "ownerId": owner_id,
            "title": title,
            "messageCount": 1,
            "createdAt": now,
            "updatedAt": now,
        })
        r.expire(key, AgentRedisKeys.SESSION_META_TTL)
    else:
        r.hincrby(key, "messageCount", 1)
        r.hset(key, "updatedAt", now)
        r.expire(key, AgentRedisKeys.SESSION_META_TTL)
    r.zadd(AgentRedisKeys.SESSION_OWNER_INDEX.format(owner_id), {thread_id: now})
    r.expire(AgentRedisKeys.SESSION_OWNER_INDEX.format(owner_id),
             AgentRedisKeys.SESSION_META_TTL)


def get_session(thread_id: str) -> dict | None:
    return get_redis().hgetall(AgentRedisKeys.SESSION_META.format(thread_id)) or None


def list_sessions(owner_id: str, current: int = 1) -> tuple[list[dict], int]:
    """按 owner 索引分页读取会话，避免扫描所有用户的 Redis key。"""
    r = get_redis()
    sessions = []
    index_key = AgentRedisKeys.SESSION_OWNER_INDEX.format(owner_id)
    thread_ids = r.zrevrange(index_key, 0, -1)
    for thread_id in thread_ids:
        meta = r.hgetall(AgentRedisKeys.SESSION_META.format(thread_id))
        if meta and meta.get("ownerId") == owner_id:
            sessions.append({
                "threadId": thread_id,
                "title": meta.get("title", ""),
                "messageCount": int(meta.get("messageCount", 0)),
                "createdAt": int(meta.get("createdAt", 0)),
                "updatedAt": int(meta.get("updatedAt", 0)),
            })
        elif thread_id:
            # Hash 已过期时清除索引中的孤儿成员。
            r.zrem(index_key, thread_id)
    total = len(sessions)
    page = sessions[(current - 1) * 10: current * 10]
    return page, total


def delete_session(thread_id: str, owner_id: str) -> None:
    r = get_redis()
    r.delete(AgentRedisKeys.SESSION_META.format(thread_id))
    r.zrem(AgentRedisKeys.SESSION_OWNER_INDEX.format(owner_id), thread_id)
