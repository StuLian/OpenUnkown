"""trace 运行记录（runs 表）：按用户记录每轮对话的完整原始报文与自动标记。

列表查询只返回摘要字段（不含体积大的原始报文），详情按 run_id 单独取全文，
避免 Trace 轨迹面板列表页一次性拉出大量原始报文拖慢加载。
"""
from __future__ import annotations

import json
import time

from backend.store.db import _lock, get_conn
from backend.store.feedback import list_feedback_for_run

# 列表返回时 final_answer 的截断长度（仅用于预览，详情返回全文）
_ANSWER_PREVIEW = 200


def _dumps(obj) -> str:
    """对象序列化为 JSON 字符串（保留中文，不转义）。"""
    return json.dumps(obj, ensure_ascii=False)


def insert_run(run: dict) -> None:
    """写入一条 run trace。run 字段由 tracing.collector.TraceCollector.finalize 产出。"""
    with _lock:
        get_conn().execute(
            "INSERT INTO runs"
            " (id, user_id, session_id, model, mode, prompt_version, platform, input_text,"
            "  messages, tool_calls, tool_outputs, retrieved_docs, final_answer,"
            "  usage, latency_ms, error, flags, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run["id"],
                run["user_id"],
                run["session_id"],
                run["model"],
                run["mode"],
                run.get("prompt_version", ""),
                run.get("platform", ""),
                run.get("input_text", ""),
                _dumps(run.get("messages", [])),
                _dumps(run.get("tool_calls", [])),
                _dumps(run.get("tool_outputs", [])),
                _dumps(run.get("retrieved_docs", [])),
                run.get("final_answer", ""),
                _dumps(run.get("usage", {})),
                run.get("latency_ms", 0),
                run.get("error"),
                _dumps(run.get("flags", [])),
                run.get("created_at", time.time()),
            ),
        )
        get_conn().commit()


def _row_to_summary(r: dict) -> dict:
    """把列表行转成摘要 dict（解析 JSON 字段、截断长文本）。"""
    answer = r.get("final_answer") or ""
    return {
        "id": r["id"],
        "session_id": r["session_id"],
        "model": r["model"],
        "mode": r["mode"],
        "input_text": r.get("input_text") or "",
        "final_answer_preview": answer[:_ANSWER_PREVIEW],
        "latency_ms": r.get("latency_ms") or 0,
        "error": r.get("error"),
        "flags": json.loads(r.get("flags") or "[]"),
        "feedback_count": r.get("feedback_count") or 0,
        "created_at": r["created_at"],
    }


def list_runs(
    user_id: str,
    flag: str | None = None,
    model: str | None = None,
    mode: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """按用户分页列出 run 摘要，可按自动/用户 flag、模型、模式筛选。

    flag 同时匹配 runs.flags（自动标记）与 feedback.tags（用户反馈标签），
    因此「幻觉」「工具异常」等用户标签与「tool_error」「no_answer」等自动标记
    都能作为筛选条件。
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where = ["r.user_id = ?"]
    params: list = [user_id]
    if flag:
        where.append(
            "(r.flags LIKE ? OR EXISTS ("
            " SELECT 1 FROM feedback fb WHERE fb.run_id = r.id AND fb.tags LIKE ?))"
        )
        params.extend([f'%"{flag}"%', f'%"{flag}"%'])
    if model:
        where.append("r.model = ?")
        params.append(model)
    if mode:
        where.append("r.mode = ?")
        params.append(mode)
    where_sql = " AND ".join(where)

    with _lock:
        rows = get_conn().execute(
            "SELECT r.id, r.session_id, r.model, r.mode, r.input_text,"
            " r.final_answer, r.latency_ms, r.error, r.flags, r.created_at,"
            " (SELECT COUNT(*) FROM feedback fb WHERE fb.run_id = r.id)"
            "   AS feedback_count"
            f" FROM runs r WHERE {where_sql}"
            " ORDER BY r.created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_row_to_summary(dict(r)) for r in rows]


def count_runs(
    user_id: str,
    flag: str | None = None,
    model: str | None = None,
    mode: str | None = None,
) -> int:
    """与 list_runs 相同筛选条件下的总数（用于前端分页）。"""
    where = ["user_id = ?"]
    params: list = [user_id]
    if flag:
        where.append(
            "(flags LIKE ? OR EXISTS ("
            " SELECT 1 FROM feedback fb WHERE fb.run_id = runs.id AND fb.tags LIKE ?))"
        )
        params.extend([f'%"{flag}"%', f'%"{flag}"%'])
    if model:
        where.append("model = ?")
        params.append(model)
    if mode:
        where.append("mode = ?")
        params.append(mode)
    where_sql = " AND ".join(where)
    with _lock:
        row = get_conn().execute(
            f"SELECT COUNT(*) AS n FROM runs WHERE {where_sql}", params
        ).fetchone()
    return int(row["n"]) if row else 0


def get_run(user_id: str, run_id: str) -> dict | None:
    """按 id 取完整 trace（含原始报文、工具调用、召回、用量与反馈）。"""
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM runs WHERE id = ? AND user_id = ?",
            (run_id, user_id),
        ).fetchone()
    if not row:
        return None
    r = dict(row)
    return {
        "id": r["id"],
        "user_id": r["user_id"],
        "session_id": r["session_id"],
        "model": r["model"],
        "mode": r["mode"],
        "platform": r["platform"],
        "prompt_version": r.get("prompt_version", ""),
        "input_text": r["input_text"],
        "messages": json.loads(r["messages"] or "[]"),
        "tool_calls": json.loads(r["tool_calls"] or "[]"),
        "tool_outputs": json.loads(r["tool_outputs"] or "[]"),
        "retrieved_docs": json.loads(r["retrieved_docs"] or "[]"),
        "final_answer": r["final_answer"],
        "usage": json.loads(r["usage"] or "{}"),
        "latency_ms": r["latency_ms"],
        "error": r["error"],
        "flags": json.loads(r["flags"] or "[]"),
        "created_at": r["created_at"],
        "feedback": list_feedback_for_run(run_id, user_id),
    }
