"""混合检索 RRF 融合纯逻辑测试。"""

from app.rag.es_hybrid import _rrf_merge


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
