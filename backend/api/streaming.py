"""SSE 流式回答的公共逻辑：消息打包、消息转字典、流式生成。"""
from __future__ import annotations

import json
import logging

from fastapi import Request
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from backend import store
from backend.agent.graph import get_graph
from backend.agent.memory import schedule_extraction
from backend.agent.prompts import PROMPT_VERSION
from backend.api.messages import build_attachment_messages, message_to_dict
from backend.tracing import TraceCollector
from backend.auth.service import resolve_api_key
from backend.config import (
    DEFAULT_PLATFORM,
    VISION_MODEL,
    get_platform,
    mode_enables_thinking,
)

logger = logging.getLogger(__name__)


def sse_event(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _persist_trace(collector: TraceCollector) -> None:
    """把一轮 trace 落库；落库失败只告警，不影响主流程。"""
    try:
        store.insert_run(collector.finalize())
    except Exception as e:  # noqa: BLE001
        logger.warning("[trace] 落库失败: %s", e)


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


async def _pending_confirm(graph, config: dict) -> dict | None:
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


async def _drain_pending_confirm(graph, config: dict, request: Request) -> bool:
    """若该会话残留未确认的命令执行（用户刷新/切换会话后重发），先自动取消并跑完。

    不把取消结果推给前端，只保证 checkpoint 干净，避免阻塞后续新消息。返回是否发生过取消。
    """
    if await _pending_confirm(graph, config) is None:
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


async def _stream_turn(
    graph,
    config: dict,
    stream_input,
    mode: str,
    request: Request,
    user_id: str,
    session_id: str,
    model: str,
):
    """跑完一轮图并产出 SSE 事件 dict（不含 model/mode/notice 头与 [DONE]）。

    命令执行在 tools 节点被 interrupt 停住时，产出 confirm 事件且不产 usage；
    整轮正常结束时产出 usage（并落 usage_log）；无论何种结束都落一条 run trace。
    """
    collector = (config.get("configurable") or {}).get("trace_collector")
    usage = None
    answer = ""
    try:
        async for chunk, meta in graph.astream(
            stream_input, config=config, stream_mode="messages"
        ):
            # 客户端已断开则停止生成，async 生成器关闭会取消底层请求
            if await request.is_disconnected():
                break

            node = meta.get("langgraph_node")

            # tools 节点：推送工具调用详情给前端做透明化提示
            if node == "tools":
                # ToolMessage：工具执行完毕，推送结果摘要
                if getattr(chunk, "type", None) == "tool":
                    yield {
                        "tool_result": {
                            "id": chunk.tool_call_id,
                            "tool": chunk.name,
                            "output": chunk.content[:300]
                            if isinstance(chunk.content, str)
                            else str(chunk.content)[:300],
                        }
                    }
                continue

            if node != "chat":
                continue

            # chat 节点：在 AI 开始生成正文之前，先推送本轮的 tool_calls 信息
            # 流式下同一个 tool_call 会分多个 chunk 到达，仅在 id 存在时推送一次
            if getattr(chunk, "tool_calls", None):
                for tc in chunk.tool_calls:
                    tc_id = tc.get("id")
                    if not tc_id:
                        continue
                    yield {
                        "tool_call": {
                            "id": tc_id,
                            "tool": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                    }

            # 累积 token 用量(通常在最后一个 chunk 上)
            if getattr(chunk, "usage_metadata", None):
                usage = chunk.usage_metadata
            # 仅思考模式推送推理过程(reasoning_content)；快速模式保持直接回答，不展示思考
            if mode_enables_thinking(mode):
                reasoning = (
                    chunk.additional_kwargs.get("reasoning_content")
                    if getattr(chunk, "additional_kwargs", None)
                    else None
                )
                if isinstance(reasoning, str) and reasoning:
                    yield {"thinking": reasoning}
            # 工具调用阶段 content 可能是空串或非字符串，只把最终自然语言增量推给前端
            text = getattr(chunk, "content", None)
            if isinstance(text, str) and text:
                answer += text
                yield {"delta": text}
    except Exception as exc:  # noqa: BLE001
        yield {"error": str(exc)}
        if collector is not None:
            collector.set_error(str(exc))

    # 图若停在命令执行待确认处，产出 confirm 事件；此时轮次未完成，不产 usage。
    confirm = await _pending_confirm(graph, config)
    if confirm is not None:
        if collector is not None:
            collector.set_pending_confirm()
        yield {"confirm": confirm}

    if usage:
        store.log_usage(user_id, session_id, model, mode, usage)
        if confirm is None:
            yield {"usage": usage}

    # 落 trace：正常结束、异常、停在确认处都落一条 run，供 Trace 轨迹面板复盘。
    if collector is not None:
        collector.set_answer(answer)
        if usage:
            collector.set_usage(usage)
        _persist_trace(collector)
        # 长记忆抽取放后台执行：不阻塞本次响应、失败静默（记忆是增强，不阻塞主流程）。
        cfg = config.get("configurable") or {}
        schedule_extraction(
            cfg.get("user_id") or "",
            collector.input_text,
            answer,
            cfg.get("api_key") or "",
            get_platform(cfg.get("platform") or DEFAULT_PLATFORM)["base_url"],
        )


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
    await _drain_pending_confirm(graph, config, request)

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

    async for ev in _stream_turn(
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

    async for ev in _stream_turn(
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
