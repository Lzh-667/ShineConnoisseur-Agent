"""画像提取与惰性刷新。

- 规则聚合：收藏 → 类型/演员/导演/地区频次；影评打分 → 评分倾向
- 惰性刷新：用户行为（收藏/发评）时间晚于画像更新时间则重算
- 对话偏好（save_preference）合并进 scene/watch 字段，confidence=high 才进画像
"""

from datetime import datetime

from app.memory import store
from app.memory.models import AgentUserProfile
from app.services import mysql, profile as profile_service


def build_profile(user_id: int) -> AgentUserProfile:
    prefs = profile_service.aggregate_user_preferences(user_id)
    return AgentUserProfile(
        user_id=user_id,
        genre_prefs=prefs["genrePrefs"],
        actor_prefs=prefs["actorPrefs"],
        director_prefs=prefs["directorPrefs"],
        region_prefs=prefs["regionPrefs"],
        rating_tendency=prefs["ratingTendency"],
        scene_prefs={},
        watch_prefs={},
        profile_summary=_summarize(prefs),
    )


def _summarize(prefs: dict) -> str:
    parts = []
    if prefs.get("genrePrefs"):
        parts.append("偏好类型：" + "/".join(prefs["genrePrefs"].keys()))
    if prefs.get("directorPrefs"):
        parts.append("常看导演：" + "/".join(prefs["directorPrefs"].keys()))
    rt = prefs.get("ratingTendency") or {}
    if rt.get("count"):
        parts.append(f"打分习惯：平均 {rt['avg']} 分（{rt['count']} 部）")
    if prefs.get("favoriteCount"):
        parts.append(f"收藏 {prefs['favoriteCount']} 部电影")
    if prefs.get("scenePrefs"):
        parts.append("观影场景：" + "/".join(prefs["scenePrefs"].keys()))
    if prefs.get("watchPrefs"):
        parts.append("观影习惯：" + "/".join(prefs["watchPrefs"].keys()))
    return "；".join(parts) or "暂无足够行为数据"


def _summarize_profile(p: AgentUserProfile) -> str:
    """基于画像对象重建摘要（对话偏好更新后调用）。"""
    return _summarize({
        "genrePrefs": p.genre_prefs or {},
        "directorPrefs": p.director_prefs or {},
        "ratingTendency": p.rating_tendency or {},
        "scenePrefs": p.scene_prefs or {},
        "watchPrefs": p.watch_prefs or {},
    })


def is_stale(user_id: int, updated_at) -> bool:
    if updated_at is None:
        return True
    latest = mysql.get_user_activity_latest(user_id)
    if not latest or latest.startswith("1970"):
        return False
    return latest > str(updated_at)


def get_or_refresh(user_id: int) -> dict:
    """画像读取入口：Redis 缓存 → 库 → 惰性重算。返回 dict。"""
    cached = store.get_cached_profile(user_id)
    if cached and cached.get("updatedAt") and not is_stale(user_id, cached["updatedAt"]):
        return cached

    profile = store.get_profile(user_id)
    if profile and not is_stale(user_id, profile.updated_at):
        store.cache_profile(user_id)
        return _to_dict(profile)

    profile = build_profile(user_id)
    store.save_profile(profile)
    return _to_dict(profile)


def record_dialogue_preference(user_id: int, pref_type: str, values: list[str],
                               confidence: str) -> str:
    """对话中提取的偏好：写入事件表；high 置信度合并进画像。"""
    if pref_type not in ("scene", "watch", "genre", "actor", "director", "region"):
        return f"不支持的偏好类型 {pref_type}"

    for v in values[:3]:
        store.add_preference_event(user_id, source=3, item_type=pref_type, item_value=v)

    if confidence == "high":
        profile = store.get_profile(user_id) or build_profile(user_id)
        field_map = {
            "scene": "scene_prefs",
            "watch": "watch_prefs",
            "genre": "genre_prefs",
            "actor": "actor_prefs",
            "director": "director_prefs",
            "region": "region_prefs",
        }
        field = field_map[pref_type]
        prefs = dict(getattr(profile, field) or {})
        for v in values[:3]:
            prefs[v] = prefs.get(v, 0) + 1
        setattr(profile, field, prefs)
        profile.profile_summary = _summarize_profile(profile)
        store.save_profile(profile)
        return f"偏好已记录并更新画像：{pref_type}={values[:3]}"
    return f"偏好已记录（低置信度，仅存档，不影响画像）：{pref_type}={values[:3]}"


def _to_dict(p: AgentUserProfile) -> dict:
    return {
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
    }
