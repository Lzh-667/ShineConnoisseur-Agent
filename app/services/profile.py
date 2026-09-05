"""用户偏好画像（第一版只读聚合，供推荐加权；阶段 5 扩展为长期记忆）。

聚合来源：收藏电影的属性频次 + 影评评分行为。不做持久化，每次实时聚合（数据量小）。
"""

from collections import Counter

from app.services import mysql


def aggregate_user_preferences(user_id: int) -> dict:
    """返回 {genrePrefs, actorPrefs, directorPrefs, regionPrefs, ratingTendency, favoriteCount}。"""
    fav_ids = mysql.get_user_favorite_movie_ids(user_id)
    fav_movies = mysql.get_movies_by_ids(fav_ids)

    genre_counter: Counter = Counter()
    actor_counter: Counter = Counter()
    director_counter: Counter = Counter()
    region_counter: Counter = Counter()
    for m in fav_movies:
        for g in (m.get("genre") or "").split(","):
            if g:
                genre_counter[g] += 1
        for a in (m.get("actors") or "").split(",")[:4]:
            if a:
                actor_counter[a] += 1
        for d in (m.get("director") or "").split(","):
            if d:
                director_counter[d] += 1
        if m.get("region"):
            region_counter[m["region"]] += 1

    rated = mysql.get_user_rated_movies(user_id)
    ratings = [r["rating"] for r in rated if r.get("rating")]

    return {
        "genrePrefs": dict(genre_counter.most_common(5)),
        "actorPrefs": dict(actor_counter.most_common(5)),
        "directorPrefs": dict(director_counter.most_common(3)),
        "regionPrefs": dict(region_counter.most_common(3)),
        "ratingTendency": {
            "avg": round(sum(ratings) / len(ratings), 1) if ratings else 0,
            "count": len(ratings),
            "min": min(ratings) if ratings else 0,
            "max": max(ratings) if ratings else 0,
        },
        "favoriteCount": len(fav_ids),
    }
