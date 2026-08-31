"""认证：解析 authorization header → 用户上下文（读后端 Redis 会话）。

后端登录会话存 Redis Hash `login:token:{token}`，字段 id/username/nickname/avatar。
无 token 或 token 失效 → 游客（userId=0）。
"""

from app.services.redis_client import get_redis


def resolve_user(token: str | None) -> dict:
    """返回 {userId, username, nickname, avatar, token}；游客 userId=0。"""
    if token:
        data = get_redis().hgetall(f"login:token:{token}")
        if data and data.get("id"):
            return {
                "userId": int(data["id"]),
                "username": data.get("username", ""),
                "nickname": data.get("nickname", ""),
                "avatar": data.get("avatar", ""),
                "token": token,
            }
    return {"userId": 0, "username": "", "nickname": "", "avatar": "", "token": token or ""}
