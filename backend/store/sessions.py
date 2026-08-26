"""会话元数据持久化(sessions 表)，按用户隔离。

sessions.id 是会话对外 id（前端使用），user_id 标识归属用户；
LangGraph checkpoint 的 thread_id 用 ``{user_id}:{session_id}`` 做命名空间，
保证不同用户即使会话 id 相同也不会串数据。
"""
from __future__ import annotations

import time

from backend.store.db import _lock, get_conn


def thread_id_for(user_id: str, session_id: str) -> str:
    """生成该用户会话对应的 checkpoint thread_id。"""
    return f"{user_id}:{session_id}"


def _truncate(text: str, n: int = 24) -> str:
    """把首条消息截断作为会话标题。"""
    text = text.strip().replace("\n", " ")
    return text[:n] + ("..." if len(text) > n else "")


def create_session(user_id: str, session_id: str, title: str) -> None:
    """新建会话元数据(若已存在则忽略)。"""
    now = time.time()
    with _lock:
        get_conn().execute(
            "INSERT OR IGNORE INTO sessions(id, user_id, title, created_at, updated_at)"
            " VALUES(?, ?, ?, ?, ?)",
            (session_id, user_id, _truncate(title), now, now),
        )
        get_conn().commit()


def touch_session(user_id: str, session_id: str, title: str | None = None) -> None:
    """更新会话的更新时间，可选更新标题。"""
    now = time.time()
    with _lock:
        if title:
            get_conn().execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (_truncate(title), now, session_id, user_id),
            )
        else:
            get_conn().execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, session_id, user_id),
            )
        get_conn().commit()


def get_session(user_id: str, session_id: str) -> dict | None:
    """获取属于指定用户的会话；不存在或不属于该用户返回 None。"""
    with _lock:
        row = get_conn().execute(
            "SELECT id, user_id, title, created_at, updated_at FROM sessions"
            " WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def list_sessions(user_id: str) -> list[dict]:
    """按最近更新倒序返回指定用户的会话列表。"""
    with _lock:
        rows = get_conn().execute(
            "SELECT id, user_id, title, created_at, updated_at FROM sessions"
            " WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(user_id: str, session_id: str) -> bool:
    """删除属于指定用户的会话及其全部 checkpoint 数据，返回是否删除成功。"""
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        if cur.rowcount > 0:
            tid = thread_id_for(user_id, session_id)
            # AsyncSqliteSaver 建的表(checkpoints / writes)，按命名空间后的 thread_id 清理
            for tbl in ("checkpoints", "writes"):
                conn.execute(f"DELETE FROM {tbl} WHERE thread_id = ?", (tid,))
        conn.commit()
    return cur.rowcount > 0
