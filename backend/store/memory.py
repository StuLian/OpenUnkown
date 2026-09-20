"""长期记忆存取（memories 表）：会话摘要（summary）与用户事实（fact）。

- summary：每个 (user_id, session_id) 一条，滚动覆盖，用于长对话的工作记忆摘要；
- fact：多条，带 embedding 向量，用于按 query 语义召回的长记忆（跨会话，session_id 为空）。
"""
from __future__ import annotations

import json
import time
import uuid

from backend.store.db import _lock, get_conn

KIND_SUMMARY = "summary"
KIND_FACT = "fact"


def _new_id() -> str:
    """生成记忆记录 id。"""
    return "mem-" + uuid.uuid4().hex


def save_summary(user_id: str, session_id: str, content: str) -> None:
    """写入/覆盖某会话的滚动摘要（每个会话一条，滚动更新）。"""
    now = time.time()
    with _lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM memories WHERE user_id = ? AND session_id = ? AND kind = ?",
            (user_id, session_id, KIND_SUMMARY),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                (content, now, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO memories"
                " (id, user_id, session_id, kind, content, embedding, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                (_new_id(), user_id, session_id, KIND_SUMMARY, content, now, now),
            )
        conn.commit()


def load_summary(user_id: str, session_id: str) -> str:
    """读取某会话的滚动摘要，没有则返回空串。"""
    with _lock:
        row = get_conn().execute(
            "SELECT content FROM memories"
            " WHERE user_id = ? AND session_id = ? AND kind = ?",
            (user_id, session_id, KIND_SUMMARY),
        ).fetchone()
    return row["content"] if row else ""


def add_fact(user_id: str, content: str, embedding: list[float]) -> str:
    """写入一条用户事实记忆（含向量），返回其 id。"""
    fid = _new_id()
    now = time.time()
    with _lock:
        get_conn().execute(
            "INSERT INTO memories"
            " (id, user_id, session_id, kind, content, embedding, created_at, updated_at)"
            " VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
            (fid, user_id, KIND_FACT, content, json.dumps(embedding), now, now),
        )
        get_conn().commit()
    return fid


def list_facts(user_id: str) -> list[dict]:
    """列出用户全部事实记忆（新→旧），embedding 解析为 list[float]。"""
    with _lock:
        rows = get_conn().execute(
            "SELECT id, content, embedding, created_at FROM memories"
            " WHERE user_id = ? AND kind = ? ORDER BY created_at DESC",
            (user_id, KIND_FACT),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else []
        out.append(d)
    return out


def count_facts(user_id: str) -> int:
    """统计用户事实记忆条数（用于上限裁剪）。"""
    with _lock:
        row = get_conn().execute(
            "SELECT COUNT(*) AS n FROM memories WHERE user_id = ? AND kind = ?",
            (user_id, KIND_FACT),
        ).fetchone()
    return int(row["n"]) if row else 0


def delete_fact(fact_id: str) -> None:
    """按 id 删除一条事实记忆（上限裁剪用，不做归属校验）。"""
    with _lock:
        get_conn().execute("DELETE FROM memories WHERE id = ?", (fact_id,))
        get_conn().commit()


def delete_fact_owned(user_id: str, fact_id: str) -> bool:
    """删除属于该用户的一条事实记忆，返回是否删除成功（非本人返回 False）。

    与 delete_fact 的区别：本函数把归属写进 WHERE，用于对外接口的越权防护。
    """
    with _lock:
        cur = get_conn().execute(
            "DELETE FROM memories WHERE id = ? AND user_id = ? AND kind = ?",
            (fact_id, user_id, KIND_FACT),
        )
        get_conn().commit()
    return cur.rowcount > 0


def delete_all_facts(user_id: str) -> int:
    """清空某用户的全部事实记忆，返回删除条数（只清本人）。"""
    with _lock:
        cur = get_conn().execute(
            "DELETE FROM memories WHERE user_id = ? AND kind = ?",
            (user_id, KIND_FACT),
        )
        get_conn().commit()
    return cur.rowcount
