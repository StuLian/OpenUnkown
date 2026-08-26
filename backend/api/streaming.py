"""SSE 流式回答的公共逻辑：消息打包、消息转字典、流式生成。"""
from __future__ import annotations

import json

from fastapi import Request
from langchain_core.messages import HumanMessage

from backend import store
from backend.agent.graph import get_graph
from backend.config import mode_enables_thinking


def sse_event(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def message_to_dict(m) -> dict | None:
    """把 LangChain 消息对象转成前端可用的 {role, content}。

    工具调用相关的中间消息不展示：tool 消息、以及仅包含 tool_calls 没有正文的 assistant 消息。
    """
    if m.type in ("system", "tool"):
        return None
    content = m.content if isinstance(m.content, str) else ""
    if m.type == "ai" and getattr(m, "tool_calls", None) and not content.strip():
        return None
    role = {"human": "user", "ai": "assistant"}.get(m.type, m.type)
    if role not in ("user", "assistant") or not content:
        return None
    return {"role": role, "content": content}


async def stream_answer(message: str, session_id: str, model: str, mode: str, request: Request):
    """以 SSE 方式逐 token 返回所选模型/模式的回答。

    客户端断开(点击停止)时立即中断底层生成，结束时回传 token 用量。
    首条消息自动创建会话元数据，标题取首条消息。
    思考模式下额外推送 reasoning_content(thinking 事件)，供前端展示思考过程。
    """
    # 首条消息创建会话(已存在则忽略)，并更新时间
    store.create_session(session_id, message)
    store.touch_session(session_id)

    graph = await get_graph()
    config = {
        "configurable": {"thread_id": session_id, "model": model, "mode": mode},
        # LangSmith 元信息：tags 便于过滤，metadata 便于在控制台检索本次会话/模型/模式
        "tags": ["openunknown", f"model:{model}", f"mode:{mode}"],
        "metadata": {
            "session_id": session_id,
            "model": model,
            "mode": mode,
        },
    }
    inputs = {"messages": [HumanMessage(content=message)]}
    usage: dict | None = None

    yield sse_event({"model": model, "mode": mode})

    try:
        async for chunk, meta in graph.astream(
            inputs, config=config, stream_mode="messages"
        ):
            # 客户端已断开则停止生成，async 生成器关闭会取消底层请求
            if await request.is_disconnected():
                break

            node = meta.get("langgraph_node")

            # tools 节点：推送工具调用详情给前端做透明化提示
            if node == "tools":
                # ToolMessage：工具执行完毕，推送结果摘要
                if chunk.type == "tool":
                    yield sse_event({
                        "tool_result": {
                            "id": chunk.tool_call_id,
                            "tool": chunk.name,
                            "output": chunk.content[:300] if isinstance(chunk.content, str) else str(chunk.content)[:300],
                        }
                    })
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
                    yield sse_event({
                        "tool_call": {
                            "id": tc_id,
                            "tool": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                    })

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
                    yield sse_event({"thinking": reasoning})
            # 工具调用阶段 content 可能是空串或非字符串，只把最终自然语言增量推给前端
            text = chunk.content
            if isinstance(text, str) and text:
                yield sse_event({"delta": text})
    except Exception as exc:  # noqa: BLE001
        yield sse_event({"error": str(exc)})

    if usage:
        yield sse_event({"usage": usage})
    yield "data: [DONE]\n\n"
