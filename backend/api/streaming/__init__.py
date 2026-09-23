"""SSE 流式回答入口：stream_answer / resume_answer（对外公共 API）。

内部按职责拆包（coding.md ≤300 行）：
- turn.py：单轮图执行的 SSE 事件产出（含幻觉闸门 + trace 落库 + 长记忆抽取）；
- confirm.py：命令执行 interrupt 检测与残留清理。
"""
from __future__ import annotations

import json
import logging

from fastapi import Request
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from backend import store
from backend.agent.graph import get_graph
from backend.agent.prompts import PROMPT_VERSION
from backend.api.messages import build_attachment_messages
from backend.api.streaming.confirm import drain_pending_confirm
from backend.api.streaming.turn import stream_turn
from backend.auth.service import resolve_api_key
from backend.config import DEFAULT_PLATFORM, VISION_MODEL
from backend.tracing import TraceCollector

logger = logging.getLogger(__name__)


def sse_event(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_config(
    user_id: str,
    session_id: str,
    model: str,
    mode: str,
    api_key: str,
    username: str,
    collector: TraceCollector | None = None,
) -> dict:
    """组装 LangGraph 运行配置（/chat 与 /chat/confirm 共用）。"""
    configurable = {
        "thread_id": store.thread_id_for(user_id, session_id),
        "model": model,
        "mode": mode,
        "platform": DEFAULT_PLATFORM,
        "api_key": api_key,
        "user_id": user_id,
        "session_id": session_id,
    }
    if collector is not None:
        configurable["trace_collector"] = collector
    return {
        "configurable": configurable,
        # LangSmith 元信息：tags 便于过滤，metadata 便于在控制台按字段检索。
        "tags": ["openunknown", f"user:{user_id}", f"model:{model}", f"mode:{mode}"],
        "metadata": {
            "session_id": session_id,
            "user_id": user_id,
            "user": username,
            "model": model,
            "mode": mode,
        },
    }


async def stream_answer(message: str, session_id: str, model: str, mode: str, user_id: str, request: Request, attachments: list | None = None):
    """以 SSE 方式逐 token 返回所选模型/模式的回答。

    客户端断开(点击停止)时立即中断底层生成，结束时回传 token 用量。
    首条消息自动创建会话元数据，标题取首条消息。
    思考模式下额外推送 reasoning_content(thinking 事件)，供前端展示思考过程。

    当前用户未配置 ApiKey 时直接返回错误事件，不调用任何模型（无兜底）。
    """
    # 首条消息创建会话(已存在则忽略)，并更新时间（按用户隔离）
    store.create_session(user_id, session_id, message)
    store.touch_session(user_id, session_id)

    # 解析当前用户的 ApiKey；未配置则阻断，不做任何兜底
    api_key = resolve_api_key(user_id, DEFAULT_PLATFORM)
    if not api_key:
        yield sse_event({"error": "尚未配置模型 ApiKey，请先在「模型设置」中填写"})
        yield "data: [DONE]\n\n"
        return

    # 解析用户名，便于在 LangSmith 中按用户名（而非仅 user_id）检索
    user = store.get_user_by_id(user_id)
    username = user["username"] if user else user_id

    # 附件：文本正文 + 图片 OCR 文字，组装成注入用 SystemMessage（OCR 延迟到此刻执行）。
    attach_msgs, image_urls, attach_names = await build_attachment_messages(
        attachments or [], api_key
    )

    # 图片附件需要多模态模型：切换视觉模型，并关闭思考（多数视觉模型不支持 enable_thinking）
    effective_model = model
    effective_mode = mode
    if image_urls:
        effective_model = VISION_MODEL
        effective_mode = "fast"

    graph = await get_graph()
    collector = TraceCollector(
        user_id=user_id,
        session_id=session_id,
        model=effective_model,
        mode=effective_mode,
        platform=DEFAULT_PLATFORM,
        input_text=message,
        prompt_version=PROMPT_VERSION,
    )
    config = _build_config(
        user_id, session_id, effective_model, effective_mode, api_key, username, collector
    )

    # 上一轮若残留未确认的命令执行（用户中途刷新/切换会话），先自动取消，避免阻塞本轮
    await drain_pending_confirm(graph, config, request)

    # 附件名不再拼进正文，而是放到 additional_kwargs，供历史回显单独渲染成 caption
    extra_kwargs = {"attachment_names": attach_names} if attach_names else {}

    if image_urls:
        content_blocks: list[dict] = [{"type": "text", "text": message}]
        for url in image_urls:
            content_blocks.append({"type": "image_url", "image_url": {"url": url}})
        human_message = HumanMessage(content=content_blocks, additional_kwargs=extra_kwargs)
    else:
        human_message = HumanMessage(content=message, additional_kwargs=extra_kwargs)

    inputs = {"messages": [*attach_msgs, human_message]}

    yield sse_event({"model": effective_model, "mode": effective_mode})
    yield sse_event({"run_id": collector.id})
    if effective_model != model:
        yield sse_event({"notice": f"本条消息包含图片，已切换视觉模型 {effective_model} 处理"})

    async for ev in stream_turn(
        graph, config, inputs, effective_mode, request, user_id, session_id, effective_model
    ):
        yield sse_event(ev)
    yield "data: [DONE]\n\n"


async def resume_answer(
    session_id: str,
    approved: bool,
    model: str,
    mode: str,
    user_id: str,
    request: Request,
):
    """命令执行人工确认后，从 checkpoint 恢复图并继续流式输出剩余回答。

    approved=True 表示用户确认执行写操作，False 表示取消。
    """
    if not store.get_session(user_id, session_id):
        yield sse_event({"error": "会话不存在或无权访问"})
        yield "data: [DONE]\n\n"
        return

    api_key = resolve_api_key(user_id, DEFAULT_PLATFORM)
    if not api_key:
        yield sse_event({"error": "尚未配置模型 ApiKey，请先在「模型设置」中填写"})
        yield "data: [DONE]\n\n"
        return

    user = store.get_user_by_id(user_id)
    username = user["username"] if user else user_id

    graph = await get_graph()
    collector = TraceCollector(
        user_id=user_id,
        session_id=session_id,
        model=model,
        mode=mode,
        platform=DEFAULT_PLATFORM,
        input_text="[命令执行确认恢复]",
        prompt_version=PROMPT_VERSION,
    )
    config = _build_config(user_id, session_id, model, mode, api_key, username, collector)

    yield sse_event({"run_id": collector.id})

    async for ev in stream_turn(
        graph,
        config,
        Command(resume={"approved": bool(approved)}),
        mode,
        request,
        user_id,
        session_id,
        model,
    ):
        yield sse_event(ev)
    yield "data: [DONE]\n\n"
