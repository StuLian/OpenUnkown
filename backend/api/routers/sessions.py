"""会话管理相关接口。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from backend import store
from backend.agent.graph import get_graph
from backend.api.streaming import message_to_dict

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions() -> dict:
    """返回所有历史会话列表，按最近更新倒序。"""
    return {"sessions": store.list_sessions()}


@router.post("")
def create_session() -> dict:
    """新建一个空会话，返回其 id(前端也可本地生成，这里提供统一入口)。"""
    session_id = "sess-" + uuid.uuid4().hex
    store.create_session(session_id, "新对话")
    return {"id": session_id}


@router.delete("/{session_id}")
def delete_session(session_id: str) -> dict:
    """删除指定会话及其全部 checkpoint 数据。"""
    store.delete_session(session_id)
    return {"ok": True}


@router.get("/{session_id}/messages")
async def get_messages(session_id: str) -> dict:
    """从 checkpoint 恢复指定会话的历史消息。"""
    graph = await get_graph()
    config = {"configurable": {"thread_id": session_id}}
    state = await graph.aget_state(config)
    messages = state.values.get("messages", []) if state and state.values else []
    return {"messages": [d for m in messages if (d := message_to_dict(m))]}
