"""会话元信息存储（Redis Hash agent:session:meta:{threadId}）。"""

import time

from app.services.redis_client import AgentRedisKeys, get_redis


def touch_session(thread_id: str, user_id: int, message: str) -> None:
    """新建或续期会话元信息；新会话用首条消息生成标题。"""
    r = get_redis()
    key = AgentRedisKeys.SESSION_META.format(thread_id)
    now = int(time.time())
    if not r.exists(key):
        title = message.strip().replace("\n", " ")[:20] or "新对话"
        r.hset(key, mapping={
            "userId": user_id,
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


def get_session(thread_id: str) -> dict | None:
    return get_redis().hgetall(AgentRedisKeys.SESSION_META.format(thread_id)) or None


def list_sessions(user_id: int, current: int = 1) -> tuple[list[dict], int]:
    """列出某用户会话。数据量小，直接 SCAN 匹配 + 内存过滤（避免 KEYS 阻塞）。"""
    r = get_redis()
    pattern = AgentRedisKeys.SESSION_META.format("*")
    sessions = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=pattern, count=200)
        for k in keys:
            meta = r.hgetall(k)
            if meta and str(meta.get("userId")) == str(user_id):
                sessions.append({
                    "threadId": k.rsplit(":", 1)[-1],
                    "title": meta.get("title", ""),
                    "messageCount": int(meta.get("messageCount", 0)),
                    "createdAt": int(meta.get("createdAt", 0)),
                    "updatedAt": int(meta.get("updatedAt", 0)),
                })
        if cursor == 0:
            break
    sessions.sort(key=lambda s: s["updatedAt"], reverse=True)
    total = len(sessions)
    page = sessions[(current - 1) * 10: current * 10]
    return page, total


def delete_session(thread_id: str) -> None:
    get_redis().delete(AgentRedisKeys.SESSION_META.format(thread_id))
