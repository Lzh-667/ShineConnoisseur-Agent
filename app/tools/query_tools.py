"""能力1：查询工具六件套。

数据链路与后端一致：
- 热门电影/热门影评：直读 Redis ZSet movie:hot: / review:hot:
- 关键词搜索：ES bool+multiMatch（同后端加权），失败降级 MySQL LIKE
- 电影详情/影评列表：MySQL（Cache-Aside 同构，Redis 有缓存先读缓存）
"""

from langchain.tools import ToolRuntime, tool

from app.services import es_client, mysql
from app.services.es_client import MOVIE_INDEX, REVIEW_INDEX, get_es
from app.services.redis_client import get_redis
from app.tools.common import to_error, to_json


def _hot_ids(key: str, current: int) -> list[int]:
    r = get_redis()
    start, end = (current - 1) * 10, current * 10 - 1
    return [int(i) for i in r.zrevrange(key, start, end)]


@tool
def list_hot_movies(current: int = 1) -> str:
    """查询站内热门电影排行（按评分人数与评分加权排序）。分页参数 current 从 1 开始，每页 10 条。"""
    ids = _hot_ids("movie:hot:", current)
    if not ids:
        return "热门电影榜暂无数据"
    movies = mysql.get_movies_by_ids(ids)
    if not movies:
        return "热门电影榜暂无数据"
    brief = [{"id": m["id"], "title": m["title"], "rating": m["rating"],
              "ratingCount": m["ratingCount"], "genre": m["genre"], "region": m["region"]}
             for m in movies]
    return f"第{current}页热门电影（共{len(brief)}条）：" + to_json(brief)


@tool
def list_hot_reviews(current: int = 1) -> str:
    """查询站内热门影评排行（按点赞/评论的时间衰减热度分排序）。分页参数 current 从 1 开始，每页 10 条。"""
    ids = _hot_ids("review:hot:", current)
    if not ids:
        return "热门影评榜暂无数据"
    reviews = mysql.get_reviews_by_ids(ids)
    if not reviews:
        return "热门影评榜暂无数据"
    brief = [{"id": r["id"], "title": r["title"], "movieId": r["movieId"],
              "movieTitle": r["movieTitle"], "nickName": r["nickName"],
              "likeCount": r["likeCount"], "commentCount": r["commentCount"],
              "rating": r["rating"], "spoiler": r["spoiler"]} for r in reviews]
    return f"第{current}页热门影评（共{len(brief)}条）：" + to_json(brief)


@tool
def get_movie_detail(movie_id: int) -> str:
    """查询某部电影的详情：简介、导演、演员、类型、地区、上映日期、片长、站内平均评分等。参数 movie_id 为电影 id。"""
    r = get_redis()
    cached = r.get(f"movie:info:{movie_id}")
    if cached == "empty":
        return f"电影(id:{movie_id})不存在或已下架"
    if cached:
        return f"电影详情：{cached}"
    movie = mysql.get_movie_by_id(movie_id)
    if not movie:
        return f"电影(id:{movie_id})不存在或已下架"
    return f"电影详情：{to_json(movie)}"


@tool
def list_movie_reviews(movie_id: int, current: int = 1) -> str:
    """查询某部电影下的影评列表（按点赞数降序）。参数 movie_id 为电影 id，current 从 1 开始每页 10 条。"""
    movie = mysql.get_movie_by_id(movie_id)
    if not movie:
        return f"电影(id:{movie_id})不存在或已下架"
    reviews = mysql.list_reviews_by_movie(movie_id, current)
    if not reviews:
        return f"《{movie['title']}》(id:{movie_id}) 暂无影评，可建议用户成为第一个写影评的人"
    brief = [{"id": r["id"], "title": r["title"], "nickName": r["nickName"],
              "rating": r["rating"], "likeCount": r["likeCount"],
              "commentCount": r["commentCount"], "spoiler": r["spoiler"],
              "content": r["content"][:200], "createTime": r["createTime"]} for r in reviews]
    return f"《{movie['title']}》第{current}页影评（共{len(brief)}条）：" + to_json(brief)


@tool
def search_movies(keyword: str, genre: str | None = None, region: str | None = None,
                  current: int = 1) -> str:
    """按关键词搜索电影，可选按类型(genre，如 科幻/喜剧/剧情)和地区(region，如 美国/中国大陆)筛选。
    参数 keyword 为搜索词；current 从 1 开始每页 10 条。"""
    try:
        hits = es_client.search_movies(keyword, genre, region, current)
    except Exception:
        try:
            movies = mysql.search_movies_like(keyword, genre, region, current)
            hits = [{"id": m["id"], "title": m["title"]} for m in movies]
        except Exception as e:
            return to_error(str(e))
    if not hits:
        return f"未找到与「{keyword}」相关的电影"
    ids = [h["id"] for h in hits]
    movies = {m["id"]: m for m in mysql.get_movies_by_ids(ids)}
    brief = [{"id": h["id"], "title": movies.get(h["id"], {}).get("title", h["title"]),
              "rating": movies.get(h["id"], {}).get("rating", 0),
              "genre": movies.get(h["id"], {}).get("genre", ""),
              "region": movies.get(h["id"], {}).get("region", "")} for h in hits]
    return f"搜索「{keyword}」命中{len(brief)}条：" + to_json(brief)


@tool
def search_reviews(keyword: str, spoiler: int | None = None, current: int = 1) -> str:
    """按关键词搜索影评（标题/电影名/正文匹配）。参数 keyword 为搜索词；
    spoiler 传 1 表示含剧透、0 表示不含剧透、不传则不过滤；current 从 1 开始每页 10 条。"""
    try:
        hits = es_client.search_reviews(keyword, spoiler, current)
    except Exception:
        try:
            reviews = mysql.search_reviews_like(keyword, spoiler, current)
            hits = [{"id": r["id"], "title": r["title"]} for r in reviews]
        except Exception as e:
            return to_error(str(e))
    if not hits:
        return f"未找到与「{keyword}」相关的影评"
    reviews = {r["id"]: r for r in mysql.get_reviews_by_ids([h["id"] for h in hits])}
    brief = [{"id": h["id"], "title": reviews.get(h["id"], {}).get("title", h["title"]),
              "movieId": reviews.get(h["id"], {}).get("movieId"),
              "movieTitle": reviews.get(h["id"], {}).get("movieTitle", ""),
              "nickName": reviews.get(h["id"], {}).get("nickName", ""),
              "likeCount": reviews.get(h["id"], {}).get("likeCount", 0),
              "spoiler": reviews.get(h["id"], {}).get("spoiler", 0)} for h in hits]
    return f"搜索「{keyword}」命中{len(brief)}条影评：" + to_json(brief)


QUERY_TOOLS = [
    list_hot_movies,
    list_hot_reviews,
    get_movie_detail,
    list_movie_reviews,
    search_movies,
    search_reviews,
]
