"""幻觉闸门评测运行器：用评测集测 check_grounding 的判定准确率。

用法：
  .venv/bin/python -m backend.eval.hallucination_eval --api-key <KEY> [--json-out report.json] [--html-out report.html]

从评测集读取 (query, answer, grounded) 三元组，逐条调 check_grounding 判定，
计算 precision / recall / F1 / 误伤率 / 漏判率，打印逐条明细与汇总，供回归门禁。
「幻觉」为正类（golden=false 表示该回答应当被判为无据）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from backend.agent.grounding import check_grounding
from backend.config import DASHSCOPE_BASE_URL

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "hallucination_cases.json"


def _load_dataset(path: str | None) -> dict:
    p = Path(path) if path else DATASET_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _classify(pred: bool | None, golden: bool) -> str:
    """把判定结果归类为 tp/fp/tn/fn。正类 = 幻觉（golden=false）。"""
    flagged = pred is False  # 判定为无据（阳性）
    if flagged and golden is False:
        return "tp"
    if flagged and golden is True:
        return "fp"
    if not flagged and golden is True:
        return "tn"
    return "fn"


async def _evaluate(api_key: str, dataset: dict, base_url: str) -> dict:
    cases = dataset["cases"]
    rows: list[dict] = []
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for c in cases:
        verdict = await check_grounding(
            c["query"], c["answer"], c.get("evidence", ""), api_key, base_url
        )
        pred = verdict.get("grounded") if verdict else None
        outcome = _classify(pred, c["grounded"])
        counts[outcome] += 1
        rows.append(
            {
                "query": c["query"],
                "answer": c["answer"],
                "golden": c["grounded"],
                "pred": pred,
                "confidence": (verdict or {}).get("confidence"),
                "reason": (verdict or {}).get("reason", ""),
                "outcome": outcome,
            }
        )
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    summary = {
        "num_cases": len(rows),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
    }
    return {"summary": summary, "rows": rows}


def _print_report(report: dict) -> None:
    s = report["summary"]
    print("=" * 72)
    print(
        f"幻觉闸门评测  cases={s['num_cases']}  "
        f"TP={s['tp']} FP={s['fp']} TN={s['tn']} FN={s['fn']}"
    )
    print(f"  precision = {s['precision']:.3f}（误伤率 = {s['false_positive_rate']:.3f}）")
    print(f"  recall    = {s['recall']:.3f}（漏判率 = {s['false_negative_rate']:.3f}）")
    print(f"  F1        = {s['f1']:.3f}")
    print("=" * 72)
    marks = {"tp": "✓ 抓对", "fn": "✗ 漏判", "fp": "✗ 误伤", "tn": "✓ 放行"}
    for r in report["rows"]:
        print(f"\n[{marks[r['outcome']]}] golden={r['golden']} pred={r['pred']} conf={r['confidence']}")
        print(f"     Q: {r['query']}")
        print(f"     A: {r['answer']}")
        if r["reason"]:
            print(f"     理由: {r['reason']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="幻觉闸门评测")
    parser.add_argument(
        "--api-key",
        default=os.getenv("EVAL_API_KEY", ""),
        help="模型服务 ApiKey（或环境变量 EVAL_API_KEY）",
    )
    parser.add_argument("--base-url", default=DASHSCOPE_BASE_URL)
    parser.add_argument("--dataset", default=None, help="评测集 JSON 路径，默认 hallucination_cases.json")
    parser.add_argument("--json-out", default=None, help="把结果 JSON 写到指定文件")
    parser.add_argument("--html-out", default=None, help="生成可视化 HTML 报告到指定文件")
    args = parser.parse_args()
    if not args.api_key:
        parser.error("缺少 ApiKey：用 --api-key 或设置环境变量 EVAL_API_KEY")
    dataset = _load_dataset(args.dataset)
    report = asyncio.run(_evaluate(args.api_key, dataset, args.base_url))
    _print_report(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入 {args.json_out}")
    if args.html_out:
        from backend.eval.report import render_hallucination_report

        Path(args.html_out).write_text(render_hallucination_report(report), encoding="utf-8")
        print(f"\nHTML 报告已写入 {args.html_out}")


if __name__ == "__main__":
    main()
