"""RAG 检索质量评估：混合检索 vs BM25 vs 向量检索（LLM 判官 + 延迟统计）。

用法（需 ES 向量索引已同步、DEEPSEEK_API_KEY 已配置）：
    .venv/Scripts/python scripts/eval_rag.py            # 全量评估
    .venv/Scripts/python scripts/eval_rag.py --top-k 3  # 自定义 top_k
    .venv/Scripts/python scripts/eval_rag.py --skip-judge   # 只测延迟不判官

产出指标：各方法平均/P50/P95 延迟、LLM 判官命中率（可写进简历的量化数字）。
"""

import argparse
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.llm import call_llm, get_reasoner_llm
from app.rag.embeddings import check_embedding_service, embed_texts
from app.rag.es_hybrid import (
    MOVIE_VEC_INDEX,
    REVIEW_VEC_INDEX,
    bm25_search,
    hybrid_search,
    knn_search,
)
from app.services.es_client import get_es

METHODS = {"bm25": bm25_search, "knn": knn_search, "hybrid": hybrid_search}

JUDGE_PROMPT = """你是检索质量评估员。请分别判断：给定用户查询，每种检索方法的结果中是否存在至少一条能正确回答该查询的结果？

用户查询：{query}
各方法检索结果（每组 top {top_k}）：
{results}

只输出严格 JSON 对象，键必须与方法名一致，值只能是 true 或 false；不要输出 Markdown 或解释。"""


def _fmt_hits(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        title = h.get("title") or "(无标题)"
        if h.get("movieTitle"):
            title += f"（影片：{h['movieTitle']}）"
        lines.append(f"- {title}")
    return "\n".join(lines) if lines else "（无结果）"


def ranking_metrics(hits: list[dict], expected_ids: list[int], top_k: int) -> dict[str, float]:
    """基于人工标注相关文档计算 Recall@K、MRR 与 nDCG@K。"""
    relevant = set(expected_ids)
    if not relevant:
        raise ValueError("expected_ids must contain at least one relevant document id")
    ranked_ids = [int(hit["id"]) for hit in hits[:top_k]]
    matched = [doc_id for doc_id in ranked_ids if doc_id in relevant]
    reciprocal_rank = 0.0
    dcg = 0.0
    for rank, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant:
            if reciprocal_rank == 0.0:
                reciprocal_rank = 1.0 / rank
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(relevant), top_k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return {
        "hit": float(bool(matched)),
        "recall": len(set(matched)) / len(relevant),
        "reciprocal_rank": reciprocal_rank,
        "ndcg": dcg / ideal_dcg if ideal_dcg else 0.0,
    }


def judge_methods(llm, query: str, hits_by_method: dict[str, list[dict]],
                  top_k: int) -> dict[str, bool]:
    """一次调用同时判断全部方法，避免独立判官调用造成横向随机偏差。"""
    non_empty = {name: hits for name, hits in hits_by_method.items() if hits}
    if not non_empty:
        return {name: False for name in hits_by_method}
    sections = [f"[{name}]\n{_fmt_hits(hits)}" for name, hits in non_empty.items()]
    prompt = JUDGE_PROMPT.format(query=query, top_k=top_k, results="\n\n".join(sections))
    answer = call_llm(llm, prompt).strip()
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"判官未返回 JSON：{answer[:80]}")
    parsed = json.loads(answer[start:end + 1])
    return {
        name: bool(parsed.get(name, False)) if hits else False
        for name, hits in hits_by_method.items()
    }


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * p))
    return sorted_values[idx]


def parse_methods(value: str) -> list[str]:
    methods = list(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    invalid = [name for name in methods if name not in METHODS]
    if not methods or invalid:
        allowed = ", ".join(METHODS)
        raise argparse.ArgumentTypeError(
            f"methods 必须是逗号分隔的以下值：{allowed}; 非法值：{', '.join(invalid)}")
    return methods


def write_markdown_report(report: dict, path: str) -> None:
    """生成可直接放入 README/简历附件的评测表。"""
    lines = [
        "# RAG 检索评测报告",
        "",
        f"- 生成时间：{report['generatedAt']}",
        f"- 查询数量：{report['queries']}",
        f"- Top K：{report['top_k']}",
        f"- LLM 判官：{'开启' if report['judgeEnabled'] else '关闭'}",
        f"- Embedding 缓存：{'已预热' if report.get('embeddingCachePrewarmed') else '未预热'}",
        "",
        "| 方法 | 平均延迟 | P50 | P95 | 错误数 | 判官命中率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in report["methods"].items():
        hit_rate = metrics.get("hit_rate")
        hit_text = f"{hit_rate * 100:.1f}%" if hit_rate is not None else "-"
        lines.append(
            f"| {name} | {metrics['avg_ms']:.1f} ms | {metrics['p50_ms']:.1f} ms | "
            f"{metrics['p95_ms']:.1f} ms | {metrics['errors']} | {hit_text} |")
    ground_truth = report.get("groundTruth")
    if ground_truth:
        lines.extend([
            "",
            f"## 人工标注检索指标（{ground_truth['labeledQueries']} 条）",
            "",
            f"| 方法 | Hit@{report['top_k']} | Recall@{report['top_k']} | MRR | nDCG@{report['top_k']} |",
            "|---|---:|---:|---:|---:|",
        ])
        for name, metrics in report["methods"].items():
            lines.append(
                f"| {name} | {metrics['hit_at_k'] * 100:.1f}% | "
                f"{metrics['recall_at_k'] * 100:.1f}% | {metrics['mrr']:.3f} | "
                f"{metrics['ndcg_at_k']:.3f} |")
    comparison = report.get("comparison")
    if comparison:
        lines.extend([
            "",
            "## 混合检索收益",
            "",
            f"- 相比 BM25 命中率变化：{comparison['hybrid_vs_bm25_pp']:+.1f} 个百分点",
            f"- 相比 KNN 命中率变化：{comparison['hybrid_vs_knn_pp']:+.1f} 个百分点",
        ])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument("--dataset", default=str(Path(__file__).parent / "eval_dataset.json"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--methods",
        type=parse_methods,
        default=list(METHODS),
        help="要评测的方法，逗号分隔：bm25,knn,hybrid",
    )
    parser.add_argument("--skip-judge", action="store_true", help="只统计延迟，不调判官 LLM")
    parser.add_argument(
        "--prewarm-embeddings",
        action="store_true",
        help="批量预热查询向量缓存，评测稳定态检索延迟",
    )
    parser.add_argument("--out", help="评估结果 JSON 输出路径")
    parser.add_argument("--markdown-out", help="评估摘要 Markdown 输出路径")
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    queries = [{**q, "index": idx}
               for idx, items in dataset.items() for q in items]
    selected_methods = {name: METHODS[name] for name in args.methods}
    llm = get_reasoner_llm() if not args.skip_judge else None

    try:
        if not get_es().ping():
            print("ES 不可达：请先启动中间件并确认 movie_vec/review_vec 已同步", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ES 连接失败：{e}", file=sys.stderr)
        sys.exit(1)

    if any(name in selected_methods for name in ("knn", "hybrid")):
        try:
            dimension = check_embedding_service()
            print(f"Embedding 前置检查通过，维度={dimension}")
        except Exception as e:
            print(f"Embedding 前置检查失败：{e}", file=sys.stderr)
            print("请更新 SILICONFLOW_API_KEY 后重试；本次未写入评测报告。", file=sys.stderr)
            sys.exit(2)

        if args.prewarm_embeddings:
            try:
                embed_texts([item["query"] for item in queries])
                print(f"Embedding 缓存预热完成，共 {len(queries)} 条查询")
            except Exception as e:
                print(f"Embedding 缓存预热失败：{e}", file=sys.stderr)
                sys.exit(2)

    if llm is not None:
        try:
            call_llm(llm, "只回复 OK")
            print("LLM 判官前置检查通过")
        except Exception as e:
            print(f"LLM 判官前置检查失败：{e}", file=sys.stderr)
            print("请更新 DEEPSEEK_API_KEY，或使用 --skip-judge。", file=sys.stderr)
            sys.exit(2)

    print(f"数据集 {len(queries)} 条查询，methods={','.join(selected_methods)}，top_k={args.top_k}，"
          f"判官={'off' if args.skip_judge else 'on'}\n")

    stats: dict[str, dict] = {
        m: {"latencies": [], "hits": 0, "errors": 0, "ranking": []}
                              for m in selected_methods}
    details = []

    for i, item in enumerate(queries, 1):
        query, index = item["query"], item["index"]
        es_index = MOVIE_VEC_INDEX if index == "movie" else REVIEW_VEC_INDEX
        row = {
            "query": query,
            "index": index,
            "category": item.get("category"),
            "expected_ids": item.get("expected_ids", []),
        }
        hits_by_method: dict[str, list[dict]] = {}
        for name, fn in selected_methods.items():
            try:
                t0 = time.perf_counter()
                hits = fn(query, es_index, args.top_k)
                hits_by_method[name] = hits
                ms = (time.perf_counter() - t0) * 1000
                stats[name]["latencies"].append(ms)
                row[f"{name}_ms"] = round(ms, 1)
                expected_ids = item.get("expected_ids") or []
                if expected_ids:
                    metrics = ranking_metrics(hits, expected_ids, args.top_k)
                    stats[name]["ranking"].append(metrics)
                    row[f"{name}_ranking"] = metrics
            except Exception as e:
                stats[name]["errors"] += 1
                row[f"{name}_error"] = str(e)[:80]
        if llm is not None:
            try:
                judgments = judge_methods(llm, query, hits_by_method, args.top_k)
                for name, hit in judgments.items():
                    stats[name]["hits"] += int(hit)
                    row[f"{name}_hit"] = hit
            except Exception as e:
                row["judge_error"] = str(e)[:80]
                for name in hits_by_method:
                    stats[name]["errors"] += 1
        details.append(row)
        timings = " ".join(
            f"{name}={row.get(f'{name}_ms', 'ERR')}ms" for name in selected_methods)
        print(f"[{i}/{len(queries)}] {query}  {timings}")

    # 汇总
    print("\n=============== RAG 检索评估报告 ===============")
    print(f"{'方法':<8}{'平均延迟':>10}{'P50':>9}{'P95':>9}{'错误':>6}"
          f"{'判官命中率':>12}")
    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "top_k": args.top_k,
        "queries": len(queries),
        "judgeEnabled": llm is not None,
        "embeddingCachePrewarmed": args.prewarm_embeddings,
        "methodsSelected": list(selected_methods),
        "methods": {},
    }
    labeled_queries = sum(bool(item.get("expected_ids")) for item in queries)
    if labeled_queries:
        report["groundTruth"] = {"labeledQueries": labeled_queries}
    for name, s in stats.items():
        lats = sorted(s["latencies"])
        avg = statistics.fmean(lats) if lats else 0.0
        hit_rate = (f"{s['hits']}/{len(queries) - s['errors']}"
                    f" = {s['hits'] / max(1, len(queries) - s['errors']) * 100:.1f}%"
                    if llm is not None else "-")
        print(f"{name:<8}{avg:>9.1f}ms{percentile(lats, 0.5):>8.1f}ms"
              f"{percentile(lats, 0.95):>8.1f}ms{s['errors']:>6}{hit_rate:>12}")
        successful = len(queries) - s["errors"]
        report["methods"][name] = {
            "avg_ms": round(avg, 1),
            "p50_ms": round(percentile(lats, 0.5), 1),
            "p95_ms": round(percentile(lats, 0.95), 1),
            "errors": s["errors"],
            "judged_hits": s["hits"],
            "hit_rate": s["hits"] / max(1, successful) if llm is not None else None,
        }
        if s["ranking"]:
            report["methods"][name].update({
                "hit_at_k": statistics.fmean(x["hit"] for x in s["ranking"]),
                "recall_at_k": statistics.fmean(x["recall"] for x in s["ranking"]),
                "mrr": statistics.fmean(x["reciprocal_rank"] for x in s["ranking"]),
                "ndcg_at_k": statistics.fmean(x["ndcg"] for x in s["ranking"]),
            })
    print("===============================================")
    if labeled_queries:
        print(f"\n========== 人工标注指标（{labeled_queries} 条，Top {args.top_k}） ==========")
        print(f"{'方法':<8}{'Hit@K':>10}{'Recall@K':>12}{'MRR':>10}{'nDCG@K':>10}")
        for name, metrics in report["methods"].items():
            if "hit_at_k" not in metrics:
                continue
            print(
                f"{name:<8}{metrics['hit_at_k'] * 100:>9.1f}%"
                f"{metrics['recall_at_k'] * 100:>11.1f}%"
                f"{metrics['mrr']:>10.3f}{metrics['ndcg_at_k']:>10.3f}"
            )
        print("===================================================")

    if llm is not None and all(name in report["methods"] for name in METHODS):
        methods = report["methods"]
        report["comparison"] = {
            "hybrid_vs_bm25_pp": round(
                (methods["hybrid"]["hit_rate"] - methods["bm25"]["hit_rate"]) * 100, 1),
            "hybrid_vs_knn_pp": round(
                (methods["hybrid"]["hit_rate"] - methods["knn"]["hit_rate"]) * 100, 1),
        }

    if args.out:
        report["details"] = details
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"详细结果已写入 {args.out}")
    if args.markdown_out:
        write_markdown_report(report, args.markdown_out)
        print(f"Markdown 摘要已写入 {args.markdown_out}")


if __name__ == "__main__":
    main()
