"""长期记忆的查看与删除接口（按用户隔离）。

对应验证报告 R10：让用户对「系统记住了什么」可见、可控。
- GET    /api/memory         列出本人事实记忆（剥离向量）
- DELETE /api/memory/{id}    删除本人一条
- DELETE /api/memory         清空本人全部
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend import store
from backend.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
def list_memories(user_id: str = Depends(get_current_user_id)) -> dict:
    """列出当前用户的长期事实记忆（新→旧），不返回 embedding。"""
    facts = store.list_facts(user_id)
    return {
        "facts": [
            {
                "id": f["id"],
                "content": f["content"],
                "created_at": f["created_at"],
            }
            for f in facts
        ],
        "total": len(facts),
    }


@router.delete("/{fact_id}")
def delete_memory(
    fact_id: str, user_id: str = Depends(get_current_user_id)
) -> dict:
    """删除一条长期记忆；不属于当前用户时返回 404（不泄露存在性）。"""
    if not store.delete_fact_owned(user_id, fact_id):
        raise HTTPException(status_code=404, detail="记忆不存在或无权访问")
    return {"ok": True}


@router.delete("")
def clear_memories(user_id: str = Depends(get_current_user_id)) -> dict:
    """清空当前用户的全部长期记忆，返回删除条数。"""
    return {"ok": True, "deleted": store.delete_all_facts(user_id)}
