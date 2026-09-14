"""工具层测试：mock MySQL/Redis/ES/LLM，覆盖查询、RAG、创作、总结工具核心分支。"""

import json

from langgraph.prebuilt.tool_node import ToolRuntime

from app.agent.context import AgentContext
from app.services import mysql
from app.tools import TOOLS_BY_NAME


def _runtime(user_id: int = 0, token: str = "") -> ToolRuntime:
    return ToolRuntime(state=None, context=AgentContext(user_id=user_id, token=token),
                       config=None, stream_writer=None, tool_call_id=None, store=None)


def _movie(**kw):
    m = {
        "id": 1, "title": "肖申克的救赎", "originalTitle": None, "cover": None,
        "director": "弗兰克·德拉邦特", "actors": "蒂姆·罗宾斯", "genre": "剧情",
        "region": "美国", "language": "英语", "releaseDate": "1994-09-10",
        "duration": 142, "summary": "希望与自由", "rating": 9.7, "ratingCount": 1000,
    }
    m.update(kw)
    return m


def _review(**kw):
    r = {
        "id": 1, "rating": 9, "title": "值得一看", "content": "内容" * 60, "spoiler": 0,
        "userId": 1, "userName": "user1", "nickName": "影迷甲", "avatar": None,
        "likeCount": 10, "commentCount": 2, "movieId": 1, "movieTitle": "肖申克的救赎",
        "createTime": "2026-01-01 00:00:00",
    }
    r.update(kw)
    return r


# ---------- 查询工具 ----------


def test_list_hot_movies(monkeypatch, fake_redis):
    fake_redis.zsets["movie:hot:"] = {"1": 100, "2": 90}
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    monkeypatch.setattr(mysql, "get_movies_by_ids",
                        lambda ids: [_movie(id=i) for i in ids])
    out = TOOLS_BY_NAME["list_hot_movies"].invoke({"current": 1})
    assert "肖申克的救赎" in out and "9.7" in out


def test_list_hot_movies_empty(monkeypatch, fake_redis):
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    out = TOOLS_BY_NAME["list_hot_movies"].invoke({"current": 1})
    assert "暂无数据" in out


def test_list_hot_reviews(monkeypatch, fake_redis):
    fake_redis.zsets["review:hot:"] = {"5": 50}
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    monkeypatch.setattr(mysql, "get_reviews_by_ids",
                        lambda ids: [_review(id=i) for i in ids])
    out = TOOLS_BY_NAME["list_hot_reviews"].invoke({"current": 1})
    assert "值得一看" in out and "影迷甲" in out


def test_get_movie_detail_cache_hit(monkeypatch, fake_redis):
    fake_redis.strings["movie:info:1"] = json.dumps(_movie(), ensure_ascii=False)
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    out = TOOLS_BY_NAME["get_movie_detail"].invoke({"movie_id": 1})
    assert "肖申克的救赎" in out


def test_get_movie_detail_cached_empty(monkeypatch, fake_redis):
    fake_redis.strings["movie:info:1"] = "empty"
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    out = TOOLS_BY_NAME["get_movie_detail"].invoke({"movie_id": 1})
    assert "不存在或已下架" in out


def test_get_movie_detail_db_miss(monkeypatch, fake_redis):
    monkeypatch.setattr("app.tools.query_tools.get_redis", lambda: fake_redis)
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: None)
    out = TOOLS_BY_NAME["get_movie_detail"].invoke({"movie_id": 999})
    assert "不存在或已下架" in out


def test_list_movie_reviews_movie_missing(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: None)
    out = TOOLS_BY_NAME["list_movie_reviews"].invoke({"movie_id": 999})
    assert "不存在或已下架" in out


def test_list_movie_reviews_empty(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie", lambda mid, cur: [])
    out = TOOLS_BY_NAME["list_movie_reviews"].invoke({"movie_id": 1})
    assert "暂无影评" in out


def test_list_movie_reviews_ok(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie",
                        lambda mid, cur: [_review()])
    out = TOOLS_BY_NAME["list_movie_reviews"].invoke({"movie_id": 1})
    assert "值得一看" in out


def test_search_movies_es_ok(monkeypatch):
    monkeypatch.setattr("app.services.es_client.search_movies",
                        lambda kw, g, r, cur: [{"id": 1, "title": "肖申克的救赎"}])
    monkeypatch.setattr(mysql, "get_movies_by_ids", lambda ids: [_movie()])
    out = TOOLS_BY_NAME["search_movies"].invoke({"keyword": "肖申克"})
    assert "命中1条" in out and "剧情" in out


def test_search_movies_es_fallback_mysql(monkeypatch):
    def boom(*a, **kw):
        raise ConnectionError("es down")

    monkeypatch.setattr("app.services.es_client.search_movies", boom)
    monkeypatch.setattr(mysql, "search_movies_like",
                        lambda kw, g, r, cur: [_movie(id=7, title="教父")])
    monkeypatch.setattr(mysql, "get_movies_by_ids", lambda ids: [_movie(id=7, title="教父")])
    out = TOOLS_BY_NAME["search_movies"].invoke({"keyword": "教父"})
    assert "命中1条" in out


def test_search_movies_both_fail(monkeypatch):
    monkeypatch.setattr("app.services.es_client.search_movies",
                        lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("es down")))
    monkeypatch.setattr(mysql, "search_movies_like",
                        lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("mysql down")))
    out = TOOLS_BY_NAME["search_movies"].invoke({"keyword": "x"})
    assert "查询失败" in out


def test_search_reviews_es_empty(monkeypatch):
    monkeypatch.setattr("app.services.es_client.search_reviews",
                        lambda kw, sp, cur: [])
    out = TOOLS_BY_NAME["search_reviews"].invoke({"keyword": "不存在"})
    assert "未找到" in out


def test_search_reviews_ok(monkeypatch):
    monkeypatch.setattr("app.services.es_client.search_reviews",
                        lambda kw, sp, cur: [{"id": 1, "title": "值得一看"}])
    monkeypatch.setattr(mysql, "get_reviews_by_ids", lambda ids: [_review()])
    out = TOOLS_BY_NAME["search_reviews"].invoke({"keyword": "救赎", "spoiler": 0})
    assert "命中1条影评" in out and "肖申克的救赎" in out


# ---------- RAG 语义检索 ----------


def test_semantic_search_movie(monkeypatch):
    monkeypatch.setattr("app.tools.rag_tools.hybrid_search_with_fallback",
                        lambda q, idx, k, g, r, sp: [{"id": 1, "title": "肖申克的救赎", "score": 0.9}])
    monkeypatch.setattr(mysql, "get_movies_by_ids", lambda ids: [_movie()])
    out = TOOLS_BY_NAME["semantic_search"].invoke({"query": "监狱题材经典电影"})
    data = json.loads(out)
    assert data["results"][0]["type"] == "movie"
    assert data["results"][0]["title"] == "肖申克的救赎"


def test_semantic_search_review(monkeypatch):
    monkeypatch.setattr("app.tools.rag_tools.hybrid_search_with_fallback",
                        lambda q, idx, k, g, r, sp: [{"id": 1, "title": "值得一看", "score": 0.8}])
    monkeypatch.setattr(mysql, "get_reviews_by_ids", lambda ids: [_review()])
    out = TOOLS_BY_NAME["semantic_search"].invoke(
        {"query": "关于希望主题的影评", "index": "review", "top_k": 3})
    data = json.loads(out)
    assert data["results"][0]["type"] == "review"
    assert data["results"][0]["snippet"].startswith("内容")


def test_semantic_search_no_hits(monkeypatch):
    monkeypatch.setattr("app.tools.rag_tools.hybrid_search_with_fallback",
                        lambda *a, **kw: [])
    out = TOOLS_BY_NAME["semantic_search"].invoke({"query": "冷门到不存在的片"})
    assert "无结果" in out


# ---------- AI 辅助创作 ----------


def test_draft_review_movie_missing(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: None)
    out = TOOLS_BY_NAME["draft_review"].invoke({"movie_id": 999})
    assert "不存在或已下架" in out


def test_draft_review_ok(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie_all",
                        lambda mid, limit: [_review()])
    monkeypatch.setattr("app.tools.creative_tools.call_llm",
                        lambda llm, prompt: "这是一篇草稿")
    monkeypatch.setattr("app.tools.creative_tools.get_llm", lambda: object())
    out = TOOLS_BY_NAME["draft_review"].invoke(
        {"movie_id": 1, "user_prompt": "从希望的角度写", "rating": 9})
    assert "影评草稿" in out and "这是一篇草稿" in out


def test_generate_review_title_ok(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr("app.tools.creative_tools.call_llm",
                        lambda llm, prompt: "1. 希望之翼")
    monkeypatch.setattr("app.tools.creative_tools.get_llm", lambda: object())
    out = TOOLS_BY_NAME["generate_review_title"].invoke({"movie_id": 1})
    assert "候选标题" in out


def test_publish_review_guest(monkeypatch):
    t = TOOLS_BY_NAME["publish_review"]
    out = t.func(_runtime(user_id=0), movie_id=1, title="t", content="c", rating=8, spoiler=0)
    assert "游客" in out


def test_publish_review_invalid_rating(monkeypatch):
    t = TOOLS_BY_NAME["publish_review"]
    out = t.func(_runtime(user_id=1, token="tok"), movie_id=1, title="t",
                 content="c", rating=11, spoiler=0)
    assert "1-10" in out


def test_publish_review_ok(monkeypatch):
    monkeypatch.setattr("app.tools.creative_tools.post_backend",
                        lambda path, body, token: {"success": True})
    t = TOOLS_BY_NAME["publish_review"]
    out = t.func(_runtime(user_id=1, token="tok"), movie_id=1, title="t",
                 content="c", rating=8, spoiler=0)
    assert "发布成功" in out


def test_publish_review_duplicate(monkeypatch):
    monkeypatch.setattr("app.tools.creative_tools.post_backend",
                        lambda path, body, token: {"success": False, "errorMsg": "数据已存在"})
    t = TOOLS_BY_NAME["publish_review"]
    out = t.func(_runtime(user_id=1, token="tok"), movie_id=1, title="t",
                 content="c", rating=8, spoiler=0)
    assert "限一条" in out


# ---------- 总结与观点分析 ----------


def test_summarize_reviews_no_reviews(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie_all", lambda mid, limit: [])
    out = TOOLS_BY_NAME["summarize_reviews"].invoke({"movie_id": 1})
    assert "暂无影评" in out


def test_summarize_reviews_ok_and_few_note(monkeypatch, ):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie_all",
                        lambda mid, limit: [_review(), _review(id=2)])
    captured = {}

    def fake_call(llm, prompt):
        captured["prompt"] = prompt
        return "口碑很好"

    monkeypatch.setattr("app.tools.summary_tools.call_llm", fake_call)
    monkeypatch.setattr("app.tools.summary_tools.get_reasoner_llm", lambda: object())
    out = TOOLS_BY_NAME["summarize_reviews"].invoke(
        {"movie_id": 1, "focus": "剧情"})
    assert "共 2 条影评" in out and "口碑很好" in out
    assert "仅供参考" in captured["prompt"]  # 影评 <3 条时提示
    assert "剧情" in captured["prompt"]


def test_analyze_review_sentiment_empty(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie_all", lambda mid, limit: [])
    out = TOOLS_BY_NAME["analyze_review_sentiment"].invoke({"movie_id": 1})
    assert json.loads(out)["ratingStats"]["count"] == 0


def test_analyze_review_sentiment_ok(monkeypatch):
    monkeypatch.setattr(mysql, "get_movie_by_id", lambda mid: _movie())
    monkeypatch.setattr(mysql, "list_reviews_by_movie_all",
                        lambda mid, limit: [_review()])
    monkeypatch.setattr("app.tools.summary_tools.call_llm",
                        lambda llm, prompt: '{"overview": "好", "positive": ["演技好"], "negative": [], "mixed": [], "ratingStats": {"avg": 9, "count": 1, "high": 9, "low": 9}}')
    monkeypatch.setattr("app.tools.summary_tools.get_reasoner_llm", lambda: object())
    out = TOOLS_BY_NAME["analyze_review_sentiment"].invoke({"movie_id": 1})
    assert json.loads(out)["positive"] == ["演技好"]


def test_parse_json_variants():
    from app.tools.summary_tools import _parse_json
    assert _parse_json('{"a": 1}') == {"a": 1}
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('```\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('前缀 {"a": 1} 后缀') == {"a": 1}
    assert _parse_json("不是 JSON") is None
