"""评测结果的 HTML 可视化报告（自包含：内联 CSS，无外部依赖，离线可打开）。

用途：
- 验收时直观查看 recall@k / MRR / nDCG、prompt 结构检查结果；
- 归档每次评测结果，便于不同模型 / 时间 / prompt 版本之间横向对比。
"""
from __future__ import annotations

import html

_CSS = """
:root { --bg:#0e0f13; --panel:#16181f; --panel2:#1e2129; --border:#2a2e39;
  --text:#e6e8ee; --muted:#9aa0ac; --accent:#6c8cff; --accent2:#8a6cff;
  --green:#5fcf80; --red:#ff6c7a; }
* { box-sizing: border-box; }
body { margin:0; background: var(--bg); color: var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.container { max-width: 920px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 20px; margin: 0 0 20px; }
h2 { font-size: 15px; margin: 28px 0 12px; color: var(--muted); font-weight:600; }
.cards { display:flex; gap:14px; flex-wrap:wrap; }
.card { flex:1; min-width:150px; background:var(--panel); border:1px solid var(--border);
  border-radius:12px; padding:18px 20px; }
.card .metric { font-size:32px; font-weight:700; letter-spacing:0.5px; }
.card.ok .metric { color: var(--green); }
.card.bad .metric { color: var(--red); }
.card .label { color: var(--muted); font-size:12px; margin-top:4px; }
.qlist, .plist { display:flex; flex-direction:column; gap:12px; }
.qrow { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:14px 16px; }
.qline { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.qtext { font-weight:600; font-size:14px; }
.qscore { font-size:13px; white-space:nowrap; }
.qscore.ok { color:var(--green); }
.qscore.bad { color:var(--red); }
.bar { display:flex; align-items:center; gap:10px; margin-top:10px; }
.bar-track { flex:1; height:8px; background:var(--panel2); border-radius:4px; overflow:hidden; }
.bar-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); border-radius:4px; }
.bar-text { color:var(--muted); font-size:12px; white-space:nowrap; }
.qdetail { margin-top:8px; font-size:12px; color:var(--muted); line-height:1.6; word-break:break-word; }
.qdetail .golden { color:var(--green); }
.qdetail .retr { color:var(--text); }
.pver { font-size:14px; color:var(--text); }
.pver b { color:var(--accent); }
.pstatus { display:inline-block; margin:12px 0 4px; padding:6px 14px; border-radius:8px; font-size:13px; font-weight:600; }
.pstatus.ok { background:rgba(95,207,128,0.12); color:var(--green); border:1px solid rgba(95,207,128,0.35); }
.pstatus.bad { background:rgba(255,108,122,0.12); color:var(--red); border:1px solid rgba(255,108,122,0.35); }
.prow { display:flex; align-items:center; gap:12px; background:var(--panel);
  border:1px solid var(--border); border-radius:10px; padding:12px 16px; }
.prow.bad { border-color:rgba(255,108,122,0.4); }
.pmark { font-size:16px; width:20px; }
.pmark.ok { color:var(--green); }
.pmark.bad { color:var(--red); }
.plabel { font-size:13.5px; font-weight:600; }
.pdetail { color:var(--red); font-size:12.5px; }
"""


def _esc(text: str) -> str:
    return html.escape(text)


def _wrap(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class=\"container\"><h1>{_esc(title)}</h1>{body}</div></body></html>"
    )


def _bar(value: float, max_v: float, text: str) -> str:
    pct = (value / max_v * 100) if max_v > 0 else 0.0
    pct = max(0.0, min(100.0, pct))
    return (
        '<div class="bar"><div class="bar-track">'
        f'<div class="bar-fill" style="width:{pct:.1f}%"></div></div>'
        f'<span class="bar-text">{_esc(text)}</span></div>'
    )


def render_rag_report(report: dict) -> str:
    """把 rag_eval 的 report 渲染为 HTML。"""
    s = report["summary"]
    k = s["top_k"]
    cards = "".join(
        f'<div class="card ok"><div class="metric">{s[name]:.3f}</div>'
        f'<div class="label">{label}</div></div>'
        for name, label in (
            ("recall@k", f"recall@{k}"),
            ("mrr", "MRR"),
            ("ndcg@k", f"nDCG@{k}"),
        )
    )
    cards += (
        f'<div class="card"><div class="metric">{s["num_queries"]}</div>'
        '<div class="label">query 数</div></div>'
    )

    rows = []
    for r in report["rows"]:
        hit = r["recall@k"]
        cls = "ok" if hit > 0 else "bad"
        rows.append(
            '<div class="qrow">'
            f'<div class="qline"><span class="qtext">{_esc(r["query"])}</span>'
            f'<span class="qscore {cls}">recall@{k}={hit:.2f}</span></div>'
            + _bar(hit, 1.0, f"mrr={r['mrr']:.2f} · ndcg={r['ndcg@k']:.2f}")
            + f'<div class="qdetail"><span class="golden">golden: {_esc(", ".join(r["relevant"]))}</span></div>'
            + f'<div class="qdetail"><span class="retr">top: {_esc(", ".join(r["retrieved"]))}</span></div>'
            + "</div>"
        )
    body = f'<div class="cards">{cards}</div><h2>逐条明细</h2><div class="qlist">{"".join(rows)}</div>'
    return _wrap("RAG 检索评测报告", body)


def render_hallucination_report(report: dict) -> str:
    """把 hallucination_eval 的 report 渲染为 HTML。"""
    s = report["summary"]
    cards = "".join(
        f'<div class="card {cls}"><div class="metric">{s[name]:.3f}</div>'
        f'<div class="label">{label}</div></div>'
        for name, label, cls in (
            ("precision", "precision（准确率）", "ok" if s["precision"] >= 0.8 else "bad"),
            ("recall", "recall（召回率）", "ok" if s["recall"] >= 0.8 else "bad"),
            ("f1", "F1", "ok" if s["f1"] >= 0.8 else "bad"),
        )
    )
    cards += (
        f'<div class="card"><div class="metric">{s["num_cases"]}</div>'
        '<div class="label">样例数</div></div>'
        f'<div class="card"><div class="metric">{s["false_positive_rate"]:.3f}</div>'
        '<div class="label">误伤率 FP/(FP+TN)</div></div>'
        f'<div class="card"><div class="metric">{s["false_negative_rate"]:.3f}</div>'
        '<div class="label">漏判率 FN/(FN+TP)</div></div>'
    )
    marks = {"tp": ("✓ 抓对", "ok"), "fn": ("✗ 漏判", "bad"), "fp": ("✗ 误伤", "bad"), "tn": ("✓ 放行", "ok")}
    rows = []
    for r in report["rows"]:
        mark, cls = marks[r["outcome"]]
        rows.append(
            '<div class="qrow">'
            f'<div class="qline"><span class="qtext">{_esc(r["query"])}</span>'
            f'<span class="qscore {cls}">{mark}（golden={"无据" if not r["golden"] else "有据"}，判为 {r["pred"]}）</span></div>'
            f'<div class="qdetail">回答：{_esc(r["answer"])}</div>'
            + (f'<div class="qdetail">理由：{_esc(r["reason"])}</div>' if r["reason"] else "")
            + "</div>"
        )
    body = f'<div class="cards">{cards}</div><h2>逐条明细</h2><div class="qlist">{"".join(rows)}</div>'
    return _wrap("幻觉闸门评测报告", body)


def render_prompt_report(version: str, results: list[dict], ok: bool) -> str:
    """把 prompt_eval 的结果渲染为 HTML。"""
    rows = []
    for r in results:
        cls = "ok" if r["passed"] else "bad"
        mark = "✓" if r["passed"] else "✗"
        if r["passed"]:
            detail = ""
        elif r["empty"]:
            detail = "（该层为空）"
        else:
            detail = f"（缺少：{', '.join(r['missing'])}）"
        rows.append(
            f'<div class="prow {cls}"><span class="pmark {cls}">{mark}</span>'
            f'<span class="plabel">{_esc(r["label"])}</span>'
            f'<span class="pdetail">{_esc(detail)}</span></div>'
        )
    status = "全部通过" if ok else "存在失败项"
    stcls = "ok" if ok else "bad"
    body = (
        f'<div class="pver">prompt 版本：<b>{_esc(version)}</b></div>'
        f'<div class="pstatus {stcls}">{status}</div>'
        f'<div class="plist" style="margin-top:12px">{"".join(rows)}</div>'
    )
    return _wrap("prompt 结构回归报告", body)
