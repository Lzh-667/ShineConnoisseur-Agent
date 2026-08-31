"""ES 客户端与关键词检索（加权与后端 MovieServiceImpl/ReviewServiceImpl 保持一致）。"""

from elasticsearch import Elasticsearch

from app.config.settings import settings

_client: Elasticsearch | None = None

MOVIE_INDEX = "movie"
REVIEW_INDEX = "review"
# 语义索引（阶段 2 创建）
MOVIE_VEC_INDEX = "movie_vec"
REVIEW_VEC_INDEX = "review_vec"

PAGE_SIZE = 10


def get_es() -> Elasticsearch:
    global _client
    if _client is None:
        _client = Elasticsearch(settings.es_url, request_timeout=10)
    return _client


def close_es() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def search_movies(keyword: str, genre: str | None = None, region: str | None = None,
                  current: int = 1) -> list[dict]:
    """电影关键词搜索（与后端同加权：title^3, originalTitle^2, director^2, actors）。"""
    must = [{
        "multi_match": {
            "query": keyword,
            "fields": ["title^3", "originalTitle^2", "director^2", "actors"],
        }
    }]
    filters = [{"term": {"status": 1}}]
    if genre:
        filters.append({"wildcard": {"genre": f"*{genre}*"}})
    if region:
        filters.append({"wildcard": {"region": f"*{region}*"}})
    resp = get_es().search(
        index=MOVIE_INDEX,
        query={"bool": {"must": must, "filter": filters}},
        from_=(current - 1) * PAGE_SIZE,
        size=PAGE_SIZE,
        source=["id", "title"],
    )
    return [{"id": h["_source"]["id"], "title": h["_source"]["title"]}
            for h in resp["hits"]["hits"]]


def search_reviews(keyword: str, spoiler: int | None = None, current: int = 1) -> list[dict]:
    """影评关键词搜索（与后端同加权：title^3, movieTitle^2, content）。"""
    must = [{
        "multi_match": {
            "query": keyword,
            "fields": ["title^3", "movieTitle^2", "content"],
        }
    }]
    filters = [{"term": {"status": 1}}]
    if spoiler is not None:
        filters.append({"term": {"spoiler": spoiler}})
    resp = get_es().search(
        index=REVIEW_INDEX,
        query={"bool": {"must": must, "filter": filters}},
        from_=(current - 1) * PAGE_SIZE,
        size=PAGE_SIZE,
        source=["id", "title"],
    )
    return [{"id": h["_source"]["id"], "title": h["_source"]["title"]}
            for h in resp["hits"]["hits"]]


def ping() -> bool:
    try:
        return bool(get_es().ping())
    except Exception:
        return False
