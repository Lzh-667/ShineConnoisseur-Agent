"""混合检索 RRF 融合与检索函数测试（mock ES 客户端）。"""

from app.rag.es_hybrid import _query_year, _rrf_merge, bm25_search, knn_search


class FakeES:
    """记录查询参数的最小 ES 客户端。"""

    def __init__(self, hits=None):
        self.calls = []
        self.hits = hits or []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"hits": {"hits": self.hits}}


def test_bm25_search_builds_query(monkeypatch):
    es = FakeES()
    monkeypatch.setattr("app.rag.es_hybrid.get_es", lambda: es)
    bm25_search("越狱", "movie_vec", 5)
    call = es.calls[0]
    assert call["size"] == 5
    assert call["source"] == ["id", "title", "movieTitle"]
    body = call["query"]["bool"]
    assert body["must"][0]["multi_match"]["query"] == "越狱"
    assert body["filter"][0] == {"term": {"status": 1}}


def test_bm25_search_maps_hits(monkeypatch):
    es = FakeES(hits=[{"_source": {"id": 1, "title": "肖申克的救赎", "movieTitle": ""}}])
    monkeypatch.setattr("app.rag.es_hybrid.get_es", lambda: es)
    hits = bm25_search("越狱", "movie_vec", 5)
    assert hits[0] == {"id": 1, "title": "肖申克的救赎", "movieTitle": "", "score": 0.0}


def test_movie_search_extracts_year_as_structured_filter(monkeypatch):
    es = FakeES()
    monkeypatch.setattr("app.rag.es_hybrid.get_es", lambda: es)
    bm25_search("1994年的经典电影", "movie_vec", 5)

    filters = es.calls[0]["query"]["bool"]["filter"]
    assert {"term": {"releaseYear": 1994}} in filters
    assert _query_year("推荐2024年科幻片") == 2024
    assert _query_year("推荐经典科幻片") is None


def test_knn_search_uses_embedding(monkeypatch):
    es = FakeES()
    monkeypatch.setattr("app.rag.es_hybrid.get_es", lambda: es)
    monkeypatch.setattr("app.rag.es_hybrid.embed_texts",
                        lambda texts: [[0.1] * 1024 for _ in texts])
    knn_search("悬疑烧脑片", "movie_vec", 3)
    knn = es.calls[0]["knn"][0]
    assert knn["field"] == "content_embedding"
    assert len(knn["query_vector"]) == 1024
    assert knn["k"] == 3


def test_rrf_merge_basic():
    """两路都命中的文档融合分最高，单路命中按排名给分。"""
    bm25 = [{"id": 1, "title": "A", "score": 0.0},
            {"id": 2, "title": "B", "score": 0.0}]
    knn = [{"id": 2, "title": "B", "score": 0.0},
           {"id": 3, "title": "C", "score": 0.0}]
    merged = _rrf_merge([bm25, knn], top_k=3)
    assert [h["id"] for h in merged] == [2, 1, 3]
    # id=2: 1/61 + 1/61；id=1: 1/61；id=3: 1/62
    assert merged[0]["score"] > merged[1]["score"] > merged[2]["score"]


def test_rrf_merge_top_k():
    hits = [{"id": i, "title": f"m{i}", "score": 0.0} for i in range(10)]
    merged = _rrf_merge([hits], top_k=3)
    assert len(merged) == 3
    assert merged[0]["id"] == 0


def test_rrf_merge_empty():
    assert _rrf_merge([], top_k=5) == []
