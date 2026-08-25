"""会话元数据持久化(sessions 表)。"""
from __future__ import annotations

import time

from backend.store.db import _lock, get_conn


def _truncate(text: str, n: int = 24) -> str:
    """把首条消息截断作为会话标题。"""
    text = text.strip().replace("\n", " ")
    return text[:n] + ("..." if len(text) > n else "")


def create_session(session_id: str, title: str) -> None:
    """新建会话元数据(若已存在则忽略)。"""
    now = time.time()
    with _lock:
        get_conn().execute(
            "INSERT OR IGNORE INTO sessions(id, title, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (session_id, _truncate(title), now, now),
        )
        get_conn().commit()


def touch_session(session_id: str, title: str | None = None) -> None:
    """更新会话的更新时间，可选更新标题。"""
    now = time.time()
    with _lock:
        if title:
            get_conn().execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (_truncate(title), now, session_id),
            )
        else:
            get_conn().execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        get_conn().commit()


def list_sessions() -> list[dict]:
    """按最近更新倒序返回会话列表。"""
    with _lock:
        rows = get_conn().execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """删除会话元数据及其全部 checkpoint 数据。"""
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        # AsyncSqliteSaver 建的表(checkpoints / writes)，按 thread_id 清理
        for tbl in ("checkpoints", "writes"):
            conn.execute(f"DELETE FROM {tbl} WHERE thread_id = ?", (session_id,))
        conn.commit()
