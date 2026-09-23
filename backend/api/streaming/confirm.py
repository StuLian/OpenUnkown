"""命令执行确认的公共逻辑：检测 interrupt 停靠、清理残留确认。

从 streaming.py 拆出，避免其继续膨胀（coding.md ≤300 行）。
"""
from __future__ import annotations

import logging

from fastapi import Request
from langgraph.types import Command

logger = logging.getLogger(__name__)


async def pending_confirm(graph, config: dict) -> dict | None:
    """若图停在命令执行待确认的 interrupt 上，返回其负载；否则返回 None。"""
    try:
        state = await graph.aget_state(config)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取图状态失败: %s", e)
        return None
    if not state or not state.next:
        return None
    for task in (state.tasks or []):
        for iv in (task.interrupts or []):
            val = getattr(iv, "value", None)
            if isinstance(val, dict) and val.get("type") == "command_write_confirmation":
                return {
                    "command": val.get("command", ""),
                    "risk": val.get("risk", ""),
                    "tool_call_id": val.get("tool_call_id", ""),
                }
    return None


async def drain_pending_confirm(graph, config: dict, request: Request) -> bool:
    """若该会话残留未确认的命令执行（用户刷新/切换会话后重发），先自动取消并跑完。

    不把取消结果推给前端，只保证 checkpoint 干净，避免阻塞后续新消息。返回是否发生过取消。
    """
    if await pending_confirm(graph, config) is None:
        return False
    try:
        async for _ in graph.astream(
            Command(resume={"approved": False}), config=config, stream_mode="messages"
        ):
            if await request.is_disconnected():
                break
    except Exception as e:  # noqa: BLE001
        logger.warning("清理残留命令确认失败: %s", e)
    return True
