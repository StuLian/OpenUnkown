"""会话管理相关接口（按用户隔离）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from backend import store
from backend.agent.graph import get_graph
from backend.api.streaming import message_to_dict
from backend.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回当前用户的历史会话列表，按最近更新倒序。"""
    return {"sessions": store.list_sessions(user_id)}


@router.post("")
def create_session(user_id: str = Depends(get_current_user_id)) -> dict:
    """新建一个空会话，返回其 id(前端也可本地生成，这里提供统一入口)。"""
    session_id = "sess-" + uuid.uuid4().hex
    store.create_session(user_id, session_id, "新对话")
    return {"id": session_id}


@router.delete("/{session_id}")
def delete_session(session_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    """删除当前用户的指定会话及其全部 checkpoint 数据。"""
    if not store.delete_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return {"ok": True}


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str, user_id: str = Depends(get_current_user_id)
) -> dict:
    """从 checkpoint 恢复当前用户指定会话的历史消息。"""
    if not store.get_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    graph = await get_graph()
    config = {"configurable": {"thread_id": store.thread_id_for(user_id, session_id)}}
    state = await graph.aget_state(config)
    messages = state.values.get("messages", []) if state and state.values else []
    return {"messages": [d for m in messages if (d := message_to_dict(m))]}
