"""RAG 检索评测运行器。

用法：
  .venv/bin/python -m backend.eval.rag_eval --api-key <KEY> [--top-k 5] [--json-out report.json]

从评测集读取 query 与 golden 酒店名，逐条调用混合检索，计算并汇总
recall@k / MRR / nDCG@k，打印逐条明细与平均指标，供 CI 回归门禁。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backend.eval.metrics import mean, mrr, ndcg_at_k, recall_at_k
from backend.rag import search_hotels

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "rag_hotels.json"


def _load_dataset(path: str | None) -> dict:
    p = Path(path) if path else DATASET_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def evaluate(api_key: str, dataset: dict, top_k: int) -> dict:
    """跑完整评测，返回逐条结果与汇总指标。"""
    queries = dataset["queries"]
    rows: list[dict] = []
    for q in queries:
        relevant = q["relevant"]
        results = search_hotels(q["query"], top_k=top_k, api_key=api_key)
        retrieved = [r["name"] for r in results]
        rows.append(
            {
                "query": q["query"],
                "relevant": relevant,
                "retrieved": retrieved,
                "recall@k": recall_at_k(relevant, retrieved, top_k),
                "mrr": mrr(relevant, retrieved),
                "ndcg@k": ndcg_at_k(relevant, retrieved, top_k),
            }
        )
    summary = {
        "top_k": top_k,
        "num_queries": len(rows),
        "recall@k": mean([r["recall@k"] for r in rows]),
        "mrr": mean([r["mrr"] for r in rows]),
        "ndcg@k": mean([r["ndcg@k"] for r in rows]),
    }
    return {"summary": summary, "rows": rows}


def _print_report(report: dict) -> None:
    s = report["summary"]
    k = s["top_k"]
    print("=" * 72)
    print(f"RAG 评测结果  top_k={k}  queries={s['num_queries']}")
    print(f"  recall@{k} = {s['recall@k']:.3f}")
    print(f"  MRR       = {s['mrr']:.3f}")
    print(f"  nDCG@{k}   = {s['ndcg@k']:.3f}")
    print("=" * 72)
    for r in report["rows"]:
        flag = "✓" if r["recall@k"] > 0 else "✗"
        print(f"\n[{flag}] {r['query']}")
        print(f"     golden: {r['relevant']}")
        print(f"     top   : {r['retrieved']}")
        print(
            f"     recall@{k}={r['recall@k']:.2f} mrr={r['mrr']:.2f} ndcg={r['ndcg@k']:.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 检索评测")
    parser.add_argument(
        "--api-key",
        default=os.getenv("EVAL_API_KEY", ""),
        help="模型服务 ApiKey（或环境变量 EVAL_API_KEY）",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dataset", default=None, help="评测集 JSON 路径，默认 rag_hotels.json")
    parser.add_argument("--json-out", default=None, help="把结果 JSON 写到指定文件")
    parser.add_argument("--html-out", default=None, help="生成可视化 HTML 报告到指定文件")
    args = parser.parse_args()
    if not args.api_key:
        parser.error("缺少 ApiKey：用 --api-key 或设置环境变量 EVAL_API_KEY")
    dataset = _load_dataset(args.dataset)
    report = evaluate(args.api_key, dataset, args.top_k)
    _print_report(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入 {args.json_out}")
    if args.html_out:
        from backend.eval.report import render_rag_report

        Path(args.html_out).write_text(render_rag_report(report), encoding="utf-8")
        print(f"\nHTML 报告已写入 {args.html_out}")


if __name__ == "__main__":
    main()
