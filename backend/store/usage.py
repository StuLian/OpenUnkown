"""token 用量日志：按用户记录每轮问答的模型/模式与 token 消耗，并提供汇总统计。"""
from __future__ import annotations

import time

from backend.store.db import _lock, get_conn


def log_usage(
    user_id: str, session_id: str, model: str, mode: str, usage: dict
) -> None:
    """记录一次问答的 token 用量；total_tokens 为 0 时跳过（如中途停止）。"""
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or 0)
    if total_tokens <= 0:
        return

    with _lock:
        get_conn().execute(
            "INSERT INTO usage_log"
            " (user_id, session_id, model, mode, input_tokens, output_tokens, total_tokens, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                session_id,
                model,
                mode,
                input_tokens,
                output_tokens,
                total_tokens,
                time.time(),
            ),
        )
        get_conn().commit()


def usage_stats(user_id: str) -> dict:
    """返回当前用户的总计、按模型与按日期聚合的用量。"""
    with _lock:
        conn = get_conn()
        totals = conn.execute(
            "SELECT COUNT(*) AS requests,"
            " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
            " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
            " COALESCE(SUM(total_tokens), 0) AS total_tokens"
            " FROM usage_log WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        by_model = [
            dict(r)
            for r in conn.execute(
                "SELECT model, COUNT(*) AS requests,"
                " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
                " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
                " COALESCE(SUM(total_tokens), 0) AS total_tokens"
                " FROM usage_log WHERE user_id = ?"
                " GROUP BY model ORDER BY total_tokens DESC",
                (user_id,),
            ).fetchall()
        ]
        by_day = [
            dict(r)
            for r in conn.execute(
                "SELECT date(created_at, 'unixepoch', 'localtime') AS date,"
                " COUNT(*) AS requests,"
                " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
                " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
                " COALESCE(SUM(total_tokens), 0) AS total_tokens"
                " FROM usage_log WHERE user_id = ?"
                " GROUP BY date ORDER BY date DESC LIMIT 30",
                (user_id,),
            ).fetchall()
        ]
    return {"totals": dict(totals), "by_model": by_model, "by_day": by_day}
