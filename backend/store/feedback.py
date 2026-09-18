"""用户反馈（feedback 表）：对某一轮 trace 的赞踩与问题标签。

标签语义（供 Trace 轨迹面板筛选）：
  hallucination 幻觉 / tool_error 工具异常 / irrelevant 答非所问 / bad 差评。
"""
from __future__ import annotations

import json
import time
import uuid

from backend.store.db import _lock, get_conn


def insert_feedback(
    user_id: str,
    run_id: str,
    session_id: str,
    rating: int,
    tags: list[str],
    comment: str = "",
) -> dict:
    """写入一条反馈，返回其摘要。rating：1 赞 / -1 踩 / 0 中性。"""
    fb_id = "fb-" + uuid.uuid4().hex
    now = time.time()
    with _lock:
        get_conn().execute(
            "INSERT INTO feedback"
            " (id, run_id, user_id, session_id, rating, tags, comment, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fb_id,
                run_id,
                user_id,
                session_id,
                int(rating),
                json.dumps(list(tags), ensure_ascii=False),
                comment,
                now,
            ),
        )
        get_conn().commit()
    return {
        "id": fb_id,
        "run_id": run_id,
        "rating": int(rating),
        "tags": list(tags),
        "comment": comment,
        "created_at": now,
    }


def list_feedback_for_run(run_id: str, user_id: str) -> list[dict]:
    """返回某条 run 的全部反馈（按时间升序），tags 解析为列表。

    user_id 用于双重校验：即便调用方已确认 run 归属，反馈也按用户过滤，
    在函数签名层面自证「不会越权读取他人反馈」。
    """
    with _lock:
        rows = get_conn().execute(
            "SELECT id, run_id, user_id, rating, tags, comment, created_at"
            " FROM feedback WHERE run_id = ? AND user_id = ? ORDER BY created_at ASC",
            (run_id, user_id),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"] or "[]")
        out.append(d)
    return out
