"""ES 向量索引管理 + BM25/knn/RRF 混合检索。

- ensure_indices()：启动时幂等创建 movie_vec / review_vec
- index_docs()：批量 upsert（含向量）
- hybrid_search()：BM25（与后端同加权）+ knn（cosine）+ RRF 融合，ES 异常降级 MySQL LIKE
"""

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.rag.embeddings import embed_texts
from app.rag.index_templates import MOVIE_VEC_INDEX_BODY, REVIEW_VEC_INDEX_BODY
from app.services import mysql
from app.services.es_client import (
    MOVIE_VEC_INDEX,
    REVIEW_VEC_INDEX,
    get_es,
)

# BM25 加权与后端 MovieServiceImpl/ReviewServiceImpl 一致
MOVIE_BM25_FIELDS = ["title^3", "originalTitle^2", "director^2", "actors", "summary"]
REVIEW_BM25_FIELDS = ["title^3", "movieTitle^2", "content"]

RRF_WINDOW = 50
RRF_RANK_CONSTANT = 60  # ES RRF 默认 rank_constant
NUM_CANDIDATES = 100

INDEX_BODIES = {
    MOVIE_VEC_INDEX: MOVIE_VEC_INDEX_BODY,
    REVIEW_VEC_INDEX: REVIEW_VEC_INDEX_BODY,
}


def ensure_indices() -> None:
    es = get_es()
    for name, body in INDEX_BODIES.items():
        if not es.indices.exists(index=name):
            es.indices.create(index=name, body=body)


def _text_of_movie(m: dict) -> str:
    parts = [m.get("title") or "", m.get("original_title") or "",
             m.get("director") or "", m.get("actors") or "",
             m.get("genre") or "", m.get("region") or "",
             m.get("summary") or ""]
    return " ".join(p for p in parts if p)


def _text_of_review(r: dict) -> str:
    parts = [r.get("title") or "", r.get("movie_title") or "", r.get("content") or ""]
    return " ".join(p for p in parts if p)


def index_movies(movies: list[dict]) -> int:
    """电影批量写入 movie_vec（含向量），返回成功条数。"""
    if not movies:
        return 0
    vecs = embed_texts([_text_of_movie(m) for m in movies])
    actions = []
    for m, vec in zip(movies, vecs):
        actions.append({
            "_op_type": "index",
            "_index": MOVIE_VEC_INDEX,
            "_id": str(m["id"]),
            "_source": {
                "id": m["id"],
                "title": m["title"],
                "originalTitle": m.get("original_title") or "",
                "director": m.get("director") or "",
                "actors": m.get("actors") or "",
                "genre": m.get("genre") or "",
                "region": m.get("region") or "",
                "summary": m.get("summary") or "",
                "status": m.get("status", 1),
                "content_embedding": vec,
            },
        })
    ok, _ = bulk(get_es(), actions, chunk_size=50, request_timeout=60)
    return ok


def index_reviews(reviews: list[dict]) -> int:
    """影评批量写入 review_vec（含向量），返回成功条数。"""
    if not reviews:
        return 0
    vecs = embed_texts([_text_of_review(r) for r in reviews])
    actions = []
    for r, vec in zip(reviews, vecs):
        actions.append({
            "_op_type": "index",
            "_index": REVIEW_VEC_INDEX,
            "_id": str(r["id"]),
            "_source": {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "movieId": r["movie_id"],
                "movieTitle": r.get("movie_title") or "",
                "spoiler": r.get("spoiler", 0),
                "status": r.get("status", 1),
                "content_embedding": vec,
            },
        })
    ok, _ = bulk(get_es(), actions, chunk_size=50, request_timeout=60)
    return ok


def delete_docs(index: str, ids: list[int]) -> None:
    if not ids:
        return
    get_es().delete_by_query(
        index=index,
        query={"terms": {"id": ids}},
        refresh=True,
    )


def index_doc_count(index: str) -> int:
    return get_es().count(index=index)["count"]


def list_index_ids(index: str, size: int = 10000) -> set[int]:
    """列出索引中全部文档 id（用于清理已下架/删除的文档）。"""
    es = get_es()
    ids = set()
    resp = es.search(
        index=index,
        query={"match_all": {}},
        size=size,
        source=False,
    )
    for h in resp["hits"]["hits"]:
        ids.add(int(h["_id"]))
    return ids


def _build_filter(index: str, genre: str | None, region: str | None,
                  spoiler: int | None) -> list[dict]:
    filters = [{"term": {"status": 1}}]
    if index == MOVIE_VEC_INDEX:
        if genre:
            filters.append({"wildcard": {"genre": f"*{genre}*"}})
        if region:
            filters.append({"wildcard": {"region": f"*{region}*"}})
    else:
        if spoiler is not None:
            filters.append({"term": {"spoiler": spoiler}})
    return filters


def _rrf_merge(hit_lists: list[list[dict]], top_k: int) -> list[dict]:
    """客户端 RRF 融合：score(d) = Σ 1/(rank_constant + rank(d))。

    ES 8.15 基础版许可证不支持服务端 RRF，此实现与 ES 服务端 RRF 语义一致。
    """
    scores: dict[int, float] = {}
    docs: dict[int, dict] = {}
    for hits in hit_lists:
        for rank, h in enumerate(hits[:RRF_WINDOW], start=1):
            scores[h["id"]] = scores.get(h["id"], 0.0) + 1.0 / (RRF_RANK_CONSTANT + rank)
            docs[h["id"]] = h
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [{**docs[doc_id], "score": round(score, 4)} for doc_id, score in ranked]


def hybrid_search(query_text: str, index: str = MOVIE_VEC_INDEX, top_k: int = 10,
                  genre: str | None = None, region: str | None = None,
                  spoiler: int | None = None) -> list[dict]:
    """BM25 + knn + 客户端 RRF 混合检索，返回 [{id, title, movieTitle, score}]（融合分降序）。"""
    es = get_es()
    fields = MOVIE_BM25_FIELDS if index == MOVIE_VEC_INDEX else REVIEW_BM25_FIELDS
    filters = _build_filter(index, genre, region, spoiler)
    candidate_size = min(top_k * 2, 100)

    def _to_hits(resp) -> list[dict]:
        out = []
        for h in resp["hits"]["hits"]:
            src = h["_source"]
            out.append({
                "id": src["id"],
                "title": src.get("title") or src.get("movieTitle") or "",
                "movieTitle": src.get("movieTitle", ""),
                "score": 0.0,
            })
        return out

    # 1) BM25 路（与后端同加权）
    bm25 = {"bool": {
        "must": [{"multi_match": {"query": query_text, "fields": fields}}],
        "filter": filters,
    }}
    bm25_resp = es.search(index=index, query=bm25, size=candidate_size,
                          source=["id", "title", "movieTitle"])

    # 2) 向量路（knn + 独立 filter）
    qvec = embed_texts([query_text])[0]
    knn = [{
        "field": "content_embedding",
        "query_vector": qvec,
        "k": candidate_size,
        "num_candidates": NUM_CANDIDATES,
        "filter": {"bool": {"filter": filters}},
    }]
    knn_resp = es.search(index=index, knn=knn, size=candidate_size,
                         source=["id", "title", "movieTitle"])

    # 3) RRF 融合
    return _rrf_merge([_to_hits(bm25_resp), _to_hits(knn_resp)], top_k)


def hybrid_search_with_fallback(query_text: str, index: str = MOVIE_VEC_INDEX,
                                top_k: int = 10, genre: str | None = None,
                                region: str | None = None,
                                spoiler: int | None = None) -> list[dict]:
    """混合检索，ES 异常时降级 MySQL LIKE（与后端降级策略一致）。"""
    try:
        return hybrid_search(query_text, index, top_k, genre, region, spoiler)
    except Exception:
        if index == MOVIE_VEC_INDEX:
            movies = mysql.search_movies_like(query_text, genre, region, 1)[:top_k]
            return [{"id": m["id"], "title": m["title"], "score": 0.0} for m in movies]
        reviews = mysql.search_reviews_like(query_text, spoiler, 1)[:top_k]
        return [{"id": r["id"], "title": r["title"], "movieTitle": r["movieTitle"],
                 "score": 0.0} for r in reviews]
