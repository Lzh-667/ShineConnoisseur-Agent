"""RAG 检索质量评估：混合检索 vs BM25 vs 向量检索（LLM 判官 + 延迟统计）。

用法（需 ES 向量索引已同步、DEEPSEEK_API_KEY 已配置）：
    .venv/Scripts/python scripts/eval_rag.py            # 全量评估
    .venv/Scripts/python scripts/eval_rag.py --top-k 3  # 自定义 top_k
    .venv/Scripts/python scripts/eval_rag.py --skip-judge   # 只测延迟不判官

产出指标：各方法平均/P50/P95 延迟、LLM 判官命中率（可写进简历的量化数字）。
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.llm import call_llm, get_reasoner_llm
from app.rag.es_hybrid import (
    MOVIE_VEC_INDEX,
    REVIEW_VEC_INDEX,
    bm25_search,
    hybrid_search,
    knn_search,
)
from app.services.es_client import get_es

METHODS = {"bm25": bm25_search, "knn": knn_search, "hybrid": hybrid_search}

JUDGE_PROMPT = """你是检索质量评估员。请判断：给定用户查询，下面的检索结果中是否存在至少一条能正确回答该查询的结果？

用户查询：{query}
检索结果（top {top_k}）：
{results}

只回答一个字：是 或 否。"""


def _fmt_hits(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        title = h.get("title") or "(无标题)"
        if h.get("movieTitle"):
            title += f"（影片：{h['movieTitle']}）"
        lines.append(f"- {title}")
    return "\n".join(lines) if lines else "（无结果）"


def judge_hit(llm, query: str, hits: list[dict], top_k: int) -> bool:
    """LLM 判官：检索结果是否能回答该查询。无结果直接判未命中，省一次调用。"""
    if not hits:
        return False
    prompt = JUDGE_PROMPT.format(query=query, top_k=top_k, results=_fmt_hits(hits))
    answer = call_llm(llm, prompt).strip()
    return answer.startswith("是")


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * p))
    return sorted_values[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument("--dataset", default=str(Path(__file__).parent / "eval_dataset.json"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--skip-judge", action="store_true", help="只统计延迟，不调判官 LLM")
    parser.add_argument("--out", help="评估结果 JSON 输出路径")
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    queries = [{"query": q["query"], "index": idx}
               for idx, items in dataset.items() for q in items]
    llm = get_reasoner_llm() if not args.skip_judge else None

    try:
        if not get_es().ping():
            print("ES 不可达：请先启动中间件并确认 movie_vec/review_vec 已同步", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ES 连接失败：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"数据集 {len(queries)} 条查询，top_k={args.top_k}，"
          f"判官={'off' if args.skip_judge else 'on'}\n")

    stats: dict[str, dict] = {m: {"latencies": [], "hits": 0, "errors": 0}
                              for m in METHODS}
    details = []

    for i, item in enumerate(queries, 1):
        query, index = item["query"], item["index"]
        es_index = MOVIE_VEC_INDEX if index == "movie" else REVIEW_VEC_INDEX
        row = {"query": query, "index": index}
        for name, fn in METHODS.items():
            try:
                t0 = time.perf_counter()
                hits = fn(query, es_index, args.top_k)
                ms = (time.perf_counter() - t0) * 1000
                stats[name]["latencies"].append(ms)
                if llm is not None:
                    hit = judge_hit(llm, query, hits, args.top_k)
                    stats[name]["hits"] += int(hit)
                    row[f"{name}_hit"] = hit
                row[f"{name}_ms"] = round(ms, 1)
            except Exception as e:
                stats[name]["errors"] += 1
                row[f"{name}_error"] = str(e)[:80]
        details.append(row)
        print(f"[{i}/{len(queries)}] {query}  "
              f"hybrid={row.get('hybrid_ms', 'ERR')}ms"
              f"{'' if llm is None else ' hit=' + str(row.get('hybrid_hit'))}")

    # 汇总
    print("\n=============== RAG 检索评估报告 ===============")
    print(f"{'方法':<8}{'平均延迟':>10}{'P50':>9}{'P95':>9}{'错误':>6}"
          f"{'判官命中率':>12}")
    report = {"top_k": args.top_k, "queries": len(queries), "methods": {}}
    for name, s in stats.items():
        lats = sorted(s["latencies"])
        avg = statistics.fmean(lats) if lats else 0.0
        hit_rate = (f"{s['hits']}/{len(queries) - s['errors']}"
                    f" = {s['hits'] / max(1, len(queries) - s['errors']) * 100:.1f}%"
                    if llm is not None else "-")
        print(f"{name:<8}{avg:>9.1f}ms{percentile(lats, 0.5):>8.1f}ms"
              f"{percentile(lats, 0.95):>8.1f}ms{s['errors']:>6}{hit_rate:>12}")
        report["methods"][name] = {
            "avg_ms": round(avg, 1),
            "p50_ms": round(percentile(lats, 0.5), 1),
            "p95_ms": round(percentile(lats, 0.95), 1),
            "errors": s["errors"],
            "judged_hits": s["hits"],
        }
    print("===============================================")

    if args.out:
        report["details"] = details
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"详细结果已写入 {args.out}")


if __name__ == "__main__":
    main()
