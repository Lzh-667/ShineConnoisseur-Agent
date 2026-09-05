"""能力6/9：RAG 语义检索工具（ES BM25+knn+RRF 混合检索）。"""

from typing import Literal

from langchain.tools import tool

from app.rag.es_hybrid import (
    MOVIE_VEC_INDEX,
    REVIEW_VEC_INDEX,
    hybrid_search_with_fallback,
)
from app.services import mysql
from app.tools.common import to_json


@tool
def semantic_search(query: str, index: Literal["movie", "review"] = "movie",
                    top_k: int = 5, genre: str | None = None,
                    region: str | None = None, spoiler: int | None = None) -> str:
    """语义检索：按意思（不要求关键词完全匹配）搜索电影或影评，支持语义相近的表达，
    如「时间旅行」「穿越时空」能互相命中。
    参数 query 为自然语言查询（如"适合全家一起看的动画电影"）；
    index 选 movie（搜电影）或 review（搜影评）；
    top_k 为返回条数（默认 5）；genre/region 可选按类型/地区过滤（仅 movie）；
    spoiler 传 1 表示含剧透、0 不含（仅 review）。返回 JSON：results 数组含 id/title/score。"""
    index_name = MOVIE_VEC_INDEX if index == "movie" else REVIEW_VEC_INDEX
    hits = hybrid_search_with_fallback(query, index_name, top_k, genre, region, spoiler)
    if not hits:
        return f"语义检索「{query}」无结果，站内暂未收录相关内容"

    if index == "movie":
        movies = {m["id"]: m for m in mysql.get_movies_by_ids([h["id"] for h in hits])}
        results = [{
            "type": "movie",
            "id": h["id"],
            "title": movies.get(h["id"], {}).get("title", h["title"]),
            "rating": movies.get(h["id"], {}).get("rating", 0),
            "genre": movies.get(h["id"], {}).get("genre", ""),
            "region": movies.get(h["id"], {}).get("region", ""),
            "score": h["score"],
        } for h in hits]
    else:
        reviews = {r["id"]: r for r in mysql.get_reviews_by_ids([h["id"] for h in hits])}
        results = [{
            "type": "review",
            "id": h["id"],
            "title": reviews.get(h["id"], {}).get("title", h["title"]),
            "movieId": reviews.get(h["id"], {}).get("movieId"),
            "movieTitle": reviews.get(h["id"], {}).get("movieTitle", h.get("movieTitle", "")),
            "likeCount": reviews.get(h["id"], {}).get("likeCount", 0),
            "spoiler": reviews.get(h["id"], {}).get("spoiler", 0),
            "snippet": (reviews.get(h["id"], {}).get("content", "") or "")[:100],
            "score": h["score"],
        } for h in hits]
    return to_json({"query": query, "results": results})


RAG_TOOLS = [semantic_search]
