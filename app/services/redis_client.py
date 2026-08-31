"""Redis 客户端与 Key 常量（agent: 前缀，镜像后端 RedisConstants 风格）。"""

from datetime import datetime

import redis

from app.config.settings import settings


class AgentRedisKeys:
    """agent 服务全部 Redis Key 定义，禁止手写 Key。"""

    # 会话元信息 Hash: {userId, title, messageCount, createdAt, updatedAt}
    SESSION_META = "agent:session:meta:{}"
    # 热门 tool 统计 ZSet（月维度），score = 调用次数
    TOOL_STATS = "agent:tool:stats:{}"
    # 用户画像缓存 String(JSON)
    PROFILE = "agent:profile:{}"
    # review_vec 增量同步游标
    SYNC_REVIEW_CURSOR = "agent:sync:review:cursor"
    # embedding 结果缓存（按文本 md5）
    EMBED_CACHE = "agent:sync:embed:cache:{}"
    # 聊天限流计数
    RATE = "agent:rate:{}"

    SESSION_META_TTL = 7 * 24 * 3600
    PROFILE_TTL = 30 * 60
    EMBED_CACHE_TTL = 30 * 24 * 3600
    RATE_WINDOW_SECONDS = 60

    @classmethod
    def tool_stats_key(cls, dt: datetime | None = None) -> str:
        return cls.TOOL_STATS.format((dt or datetime.now()).strftime("%Y%m"))


_pool: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _pool


def close_redis() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
