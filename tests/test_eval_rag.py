"""RAG 评测报告生成测试。"""

import argparse
import json
from pathlib import Path

import pytest

from scripts.eval_rag import (
    judge_methods,
    parse_methods,
    ranking_metrics,
    write_markdown_report,
)


def test_write_markdown_report(tmp_path):
    report = {
        "generatedAt": "2026-09-25T00:00:00+00:00",
        "queries": 30,
        "top_k": 5,
        "judgeEnabled": True,
        "methods": {
            "bm25": {"avg_ms": 20.0, "p50_ms": 18.0, "p95_ms": 35.0,
                     "errors": 0, "hit_rate": 0.7, "hit_at_k": 0.8,
                     "recall_at_k": 0.6, "mrr": 0.7, "ndcg_at_k": 0.65},
            "knn": {"avg_ms": 45.0, "p50_ms": 40.0, "p95_ms": 70.0,
                    "errors": 0, "hit_rate": 0.8, "hit_at_k": 0.9,
                    "recall_at_k": 0.7, "mrr": 0.8, "ndcg_at_k": 0.75},
            "hybrid": {"avg_ms": 60.0, "p50_ms": 55.0, "p95_ms": 90.0,
                       "errors": 0, "hit_rate": 0.9, "hit_at_k": 1.0,
                       "recall_at_k": 0.8, "mrr": 0.9, "ndcg_at_k": 0.85},
        },
        "groundTruth": {"labeledQueries": 25},
        "comparison": {"hybrid_vs_bm25_pp": 20.0, "hybrid_vs_knn_pp": 10.0},
    }
    output = tmp_path / "nested" / "rag.md"

    write_markdown_report(report, str(output))

    text = output.read_text(encoding="utf-8")
    assert "RAG 检索评测报告" in text
    assert "| hybrid | 60.0 ms" in text
    assert "+20.0 个百分点" in text
    assert "人工标注检索指标（25 条）" in text
    assert "| hybrid | 100.0% | 80.0% | 0.900 | 0.850 |" in text


def test_ranking_metrics_multiple_relevant_documents():
    metrics = ranking_metrics(
        [{"id": 99}, {"id": 2}, {"id": 1}, {"id": 4}],
        expected_ids=[1, 2, 3],
        top_k=3,
    )
    assert metrics["hit"] == 1.0
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["reciprocal_rank"] == 0.5
    assert 0 < metrics["ndcg"] < 1


def test_ranking_metrics_rejects_missing_ground_truth():
    with pytest.raises(ValueError):
        ranking_metrics([{"id": 1}], [], top_k=5)


def test_eval_dataset_has_reproducible_ground_truth():
    dataset_path = Path(__file__).resolve().parents[1] / "scripts" / "eval_dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    rows = [row for values in dataset.values() for row in values]
    assert len(rows) >= 25
    assert all(row.get("category") for row in rows)
    assert all(row.get("expected_ids") for row in rows)
    assert all(all(isinstance(doc_id, int) for doc_id in row["expected_ids"]) for row in rows)


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
