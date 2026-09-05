"""推荐引擎：条件匹配 / 收藏协同 / 场景模板 三路推荐 + 热度兜底。

热度分与后端热门电影算法一致：ratingCount*10 + ratingSum。
数据量小（60 部），候选池全量拉取后在内存过滤排序。
"""

import re
from collections import Counter

from app.services import mysql

# 场景模板：关键词 → (类型, 最低评分, 排除类型)
SCENE_TEMPLATES: list[tuple[list[str], dict]] = [
    (["约会", "女朋友", "男朋友", "情侣", "浪漫"], {
        "genres": ["爱情", "喜剧"], "min_rating": 7.0, "exclude_genres": ["恐怖"]}),
    (["全家", "亲子", "孩子", "小朋友", "家庭"], {
        "genres": ["动画", "家庭", "喜剧"], "min_rating": 7.0, "exclude_genres": []}),
    (["治愈", "低落", "心情不好", "难过", "温暖", "放松"], {
        "genres": ["动画", "喜剧", "剧情"], "min_rating": 7.0,
        "exclude_genres": ["恐怖", "犯罪", "惊悚", "悬疑"]}),
    (["悬疑", "烧脑", "推理", "反转"], {
        "genres": ["悬疑", "科幻", "犯罪"], "min_rating": 7.0, "exclude_genres": []}),
    (["动作", "刺激", "爽片", "打斗"], {
        "genres": ["动作", "犯罪", "科幻"], "min_rating": 7.0, "exclude_genres": []}),
    (["科幻", "硬核", "太空", "未来"], {
        "genres": ["科幻"], "min_rating": 7.5, "exclude_genres": []}),
    (["恐怖", "惊悚", "吓人"], {
        "genres": ["恐怖", "惊悚", "悬疑"], "min_rating": 6.5, "exclude_genres": []}),
    (["深夜", "独处", "一个人", "安静"], {
        "genres": ["剧情", "悬疑", "爱情"], "min_rating": 7.5, "exclude_genres": []}),
]


def hot_score(m: dict) -> float:
    return (m.get("ratingCount") or 0) * 10 + (m.get("ratingSum") or 0)


def _genre_set(m: dict) -> set[str]:
    return {g for g in (m.get("genre") or "").split(",") if g}


def _in_year_range(movie: dict, year_range: str | None) -> bool:
    if not year_range or not movie.get("releaseDate"):
        return True
    year = int(str(movie["releaseDate"])[:4])
    text = year_range.strip()
    if mm := re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", text):
        return int(mm.group(1)) <= year <= int(mm.group(2))
    if mm := re.fullmatch(r"[>＞]\s*(\d{4})", text):
        return year > int(mm.group(1))
    if mm := re.fullmatch(r"[<＜]\s*(\d{4})", text):
        return year < int(mm.group(1))
    if mm := re.fullmatch(r"(\d{4})", text):
        return year == int(mm.group(1))
    return True


def _candidate_pool() -> list[dict]:
    return [m for m in mysql.get_all_movies_for_sync() if m.get("status") == 1]


def recommend_by_conditions(genres: list[str] | None, min_rating: float = 0,
                            region: str | None = None, year_range: str | None = None,
                            exclude_ids: set[int] | None = None,
                            count: int = 5) -> list[dict]:
    """条件筛选 + 热度分排序。genres 为类型列表（任一命中即可）。

    评分两级策略：先取「有评分且达标」的严格集；不足 count 时用「暂无评分」
    的电影补足（标记 noRating），避免数据稀疏时推荐为空。
    """
    exclude_ids = exclude_ids or set()

    def _pass(m: dict) -> bool:
        if m["id"] in exclude_ids:
            return False
        if genres and not (_genre_set(m) & set(genres)):
            return False
        if region and region not in (m.get("region") or ""):
            return False
        if not _in_year_range(m, year_range):
            return False
        return True

    strict = [m for m in _candidate_pool()
              if _pass(m) and m.get("rating", 0) > 0 and m.get("rating", 0) >= min_rating]
    strict.sort(key=hot_score, reverse=True)

    if len(strict) >= count:
        return [_brief(m) for m in strict[:count]]

    unrated = [m for m in _candidate_pool() if _pass(m) and m.get("rating", 0) == 0]
    unrated.sort(key=hot_score, reverse=True)
    merged = strict + unrated
    return [_brief(m, no_rating=m.get("rating", 0) == 0) for m in merged[:count]]


def recommend_by_favorites(user_id: int, count: int = 5) -> dict:
    """收藏协同推荐：聚合收藏电影的类型偏好，推荐同类型未收藏电影；无收藏时热度兜底。"""
    fav_ids = set(mysql.get_user_favorite_movie_ids(user_id))
    rated_ids = {r["movie_id"] for r in mysql.get_user_rated_movies(user_id)}
    exclude = fav_ids | rated_ids

    if not fav_ids:
        return {
            "basis": "该用户暂无收藏，按站内热度推荐",
            "results": recommend_by_conditions(None, count=count),
        }

    fav_movies = mysql.get_movies_by_ids(list(fav_ids))
    genre_counter: Counter = Counter()
    for m in fav_movies:
        for g in _genre_set(m):
            genre_counter[g] += 1
    top_genres = [g for g, _ in genre_counter.most_common(3)]

    scored = []
    for m in _candidate_pool():
        if m["id"] in exclude:
            continue
        overlap = _genre_set(m) & set(top_genres)
        if not overlap:
            continue
        scored.append((len(overlap), hot_score(m), m))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    results = [{**_brief(m, no_rating=m.get("rating", 0) == 0),
                "matchedGenres": sorted(_genre_set(m) & set(top_genres))}
               for _, _, m in scored[:count]]
    return {
        "basis": f"根据收藏的 {len(fav_ids)} 部电影的偏好类型 {top_genres} 推荐",
        "results": results,
    }


def match_scene(scene: str) -> tuple[dict, str]:
    """场景关键词 → 模板；无匹配时返回默认模板。"""
    for keywords, template in SCENE_TEMPLATES:
        if any(k in scene for k in keywords):
            return template, keywords[0]
    return {"genres": [], "min_rating": 7.0, "exclude_genres": []}, "通用"


def recommend_for_scene(scene: str, count: int = 5,
                        exclude_ids: set[int] | None = None) -> dict:
    """场景推荐：模板映射 → 条件推荐；候选不足时放宽条件补足。"""
    exclude_ids = exclude_ids or set()
    template, scene_name = match_scene(scene)

    def _run(t: dict) -> list[dict]:
        return recommend_by_conditions(
            genres=t["genres"], min_rating=t["min_rating"],
            exclude_ids=exclude_ids, count=count * 2)

    results = [r for r in _run(template)
               if not (_genre_set(r) & set(template["exclude_genres"]))]
    if len(results) < count:
        # 放宽：评分降到 6.5，补足
        loose = {**template, "min_rating": min(template["min_rating"], 6.5),
                 "exclude_genres": []}
        seen = {r["id"] for r in results}
        results += [r for r in _run(loose)
                    if r["id"] not in seen and not (_genre_set(r) & set(template["exclude_genres"]))]
    results = results[:count]
    return {
        "scene": scene,
        "strategy": f"场景「{scene_name}」→ 类型 {template['genres']}、评分 ≥ {template['min_rating']}",
        "results": results,
    }


def compare_movies(movie_ids: list[int]) -> dict:
    """多电影对比：详情字段对齐（评分/类型/地区/导演/演员/上映/片长/简介）。"""
    movies = mysql.get_movies_by_ids(movie_ids)
    by_id = {m["id"]: m for m in movies}
    return {
        "movies": [{
            "id": i,
            "title": by_id[i]["title"] if i in by_id else "未收录",
            "rating": by_id[i]["rating"] if i in by_id else 0,
            "ratingCount": by_id[i]["ratingCount"] if i in by_id else 0,
            "genre": by_id[i].get("genre", ""),
            "region": by_id[i].get("region", ""),
            "director": by_id[i].get("director", ""),
            "actors": by_id[i].get("actors", ""),
            "releaseDate": by_id[i].get("releaseDate", ""),
            "duration": by_id[i].get("duration") or 0,
            "summary": (by_id[i].get("summary") or "")[:120],
        } for i in movie_ids],
    }


def _brief(m: dict, no_rating: bool = False) -> dict:
    return {
        "id": m["id"],
        "title": m["title"],
        "rating": m.get("rating", 0),
        "ratingCount": m.get("ratingCount", 0),
        "genre": m.get("genre", ""),
        "region": m.get("region", ""),
        "releaseDate": m.get("releaseDate", ""),
        "hotScore": hot_score(m),
        **({"noRating": True} if no_rating else {}),
    }
