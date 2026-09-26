"""RAG 评测报告生成测试。"""

import argparse

import pytest

from scripts.eval_rag import judge_methods, parse_methods, write_markdown_report


def test_write_markdown_report(tmp_path):
    report = {
        "generatedAt": "2026-09-25T00:00:00+00:00",
        "queries": 30,
        "top_k": 5,
        "judgeEnabled": True,
        "methods": {
            "bm25": {"avg_ms": 20.0, "p50_ms": 18.0, "p95_ms": 35.0,
                     "errors": 0, "hit_rate": 0.7},
            "knn": {"avg_ms": 45.0, "p50_ms": 40.0, "p95_ms": 70.0,
                    "errors": 0, "hit_rate": 0.8},
            "hybrid": {"avg_ms": 60.0, "p50_ms": 55.0, "p95_ms": 90.0,
                       "errors": 0, "hit_rate": 0.9},
        },
        "comparison": {"hybrid_vs_bm25_pp": 20.0, "hybrid_vs_knn_pp": 10.0},
    }
    output = tmp_path / "nested" / "rag.md"

    write_markdown_report(report, str(output))

    text = output.read_text(encoding="utf-8")
    assert "RAG 检索评测报告" in text
    assert "| hybrid | 60.0 ms" in text
    assert "+20.0 个百分点" in text


def test_parse_methods_deduplicates_and_preserves_order():
    assert parse_methods("hybrid,bm25,hybrid") == ["hybrid", "bm25"]


def test_parse_methods_rejects_unknown_method():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_methods("bm25,unknown")


def test_judge_methods_parses_single_comparative_response(monkeypatch):
    monkeypatch.setattr(
        "scripts.eval_rag.call_llm",
        lambda llm, prompt: '```json\n{"bm25": false, "knn": true, "hybrid": true}\n```',
    )
    hits = {
        "bm25": [{"title": "无关结果"}],
        "knn": [{"title": "相关结果"}],
        "hybrid": [{"title": "相关结果"}],
    }

    assert judge_methods(object(), "测试查询", hits, 5) == {
        "bm25": False,
        "knn": True,
        "hybrid": True,
    }


def test_judge_methods_marks_empty_results_without_call(monkeypatch):
    monkeypatch.setattr(
        "scripts.eval_rag.call_llm",
        lambda *args: pytest.fail("empty results must not call the judge"),
    )
    assert judge_methods(object(), "测试查询", {"bm25": []}, 5) == {"bm25": False}
