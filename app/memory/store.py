"""画像存取：MySQL 持久化 + Redis 30 分钟缓存。"""

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.models import AgentPreferenceEvent, AgentUserProfile, Base
from app.services.mysql import get_engine
from app.services.redis_client import AgentRedisKeys, get_redis

_sessionmaker = None


def get_session() -> Session:
    """每次返回新 Session（Session 非线程安全，不能全局共享）。"""
    global _sessionmaker
    if _sessionmaker is None:
        from sqlalchemy.orm import sessionmaker

        _sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _sessionmaker()


def ensure_tables() -> None:
    """启动时幂等建表（与 scripts/init_db.sql 一致）。"""
    Base.metadata.create_all(bind=get_engine(), checkfirst=True)


def save_profile(profile: AgentUserProfile) -> None:
    profile.updated_at = datetime.now()
    s = get_session()
    try:
        s.merge(profile)
        s.commit()
    finally:
        s.close()
    # 缓存与库保持一致
    get_redis().set(AgentRedisKeys.PROFILE.format(profile.user_id),
                    _profile_json(profile), ex=AgentRedisKeys.PROFILE_TTL)


def get_profile(user_id: int) -> AgentUserProfile | None:
    s = get_session()
    try:
        return s.get(AgentUserProfile, user_id)
    finally:
        s.close()


def cache_profile(user_id: int) -> None:
    profile = get_profile(user_id)
    if profile:
        get_redis().set(AgentRedisKeys.PROFILE.format(user_id),
                        _profile_json(profile), ex=AgentRedisKeys.PROFILE_TTL)


def get_cached_profile(user_id: int) -> dict | None:
    raw = get_redis().get(AgentRedisKeys.PROFILE.format(user_id))
    return json.loads(raw) if raw else None


def add_preference_event(user_id: int, source: int, item_type: str,
                         item_value: str, weight: int = 1) -> None:
    s = get_session()
    try:
        s.add(AgentPreferenceEvent(
            user_id=user_id, source=source, item_type=item_type,
            item_value=item_value, weight=weight, created_at=datetime.now(),
        ))
        s.commit()
    finally:
        s.close()


def _profile_json(p: AgentUserProfile) -> str:
    return json.dumps({
        "userId": p.user_id,
        "genrePrefs": p.genre_prefs or {},
        "actorPrefs": p.actor_prefs or {},
        "directorPrefs": p.director_prefs or {},
        "regionPrefs": p.region_prefs or {},
        "ratingTendency": p.rating_tendency or {},
        "scenePrefs": p.scene_prefs or {},
        "watchPrefs": p.watch_prefs or {},
        "profileSummary": p.profile_summary or "",
        "updatedAt": str(p.updated_at) if p.updated_at else None,
    }, ensure_ascii=False)
