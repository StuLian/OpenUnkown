"""SSE 流式回答的公共逻辑：消息打包、消息转字典、流式生成。"""
from __future__ import annotations

import json

from fastapi import Request
from langchain_core.messages import HumanMessage, SystemMessage

from backend import store
from backend.agent.graph import get_graph
from backend.auth.service import resolve_api_key
from backend.config import DEFAULT_PLATFORM, mode_enables_thinking
from backend.files.parser import MAX_CONTENT_CHARS


def sse_event(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def message_to_dict(m) -> dict | None:
    """把 LangChain 消息对象转成前端可用的 {role, content, usage?}。

    工具调用相关的中间消息不展示：tool 消息、以及仅包含 tool_calls 没有正文的 assistant 消息。
    assistant 消息若携带 usage_metadata，则附上 token 用量，供前端刷新后仍能展示。
    """
    if m.type in ("system", "tool"):
        return None
    content = m.content if isinstance(m.content, str) else ""
    if m.type == "ai" and getattr(m, "tool_calls", None) and not content.strip():
        return None
    role = {"human": "user", "ai": "assistant"}.get(m.type, m.type)
    if role not in ("user", "assistant") or not content:
        return None
    result = {"role": role, "content": content}
    usage_metadata = getattr(m, "usage_metadata", None)
    if usage_metadata:
        try:
            result["usage"] = {
                "input_tokens": usage_metadata.get("input_tokens", 0),
                "output_tokens": usage_metadata.get("output_tokens", 0),
                "total_tokens": usage_metadata.get("total_tokens", 0),
            }
        except Exception:
            pass
    return result


def _attachment_messages(attachments: list) -> tuple[list[SystemMessage], list[str]]:
    """把附件解析内容包装成 SystemMessage（正文不进入用户气泡），并返回附件名列表。

    附件正文以 system 消息形式持久化到 checkpoint，模型每一轮都能看到；
    message_to_dict 会过滤 system 消息，因此历史回显时不会刷出大段正文。
    """
    msgs: list[SystemMessage] = []
    names: list[str] = []
    for i, att in enumerate(attachments, 1):
        filename = (getattr(att, "filename", None) or "未命名文件")
        content = getattr(att, "content", None) or ""
        # 后端兜底截断，防止绕过前端直接提交超长内容
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n...[内容过长已截断]"
        names.append(filename)
        msgs.append(
            SystemMessage(
                content=(
                    f"[附件 {i}] 用户上传了文件《{filename}》，其解析后的纯文本内容如下，"
                    f"请结合这些内容回答用户问题：\n\n{content}"
                )
            )
        )
    return msgs, names


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

    graph = await get_graph()
    config = {
        "configurable": {
            "thread_id": store.thread_id_for(user_id, session_id),
            "model": model,
            "mode": mode,
            "platform": DEFAULT_PLATFORM,
            "api_key": api_key,
            "user_id": user_id,
        },
        # LangSmith 元信息：tags 便于过滤，metadata 便于在控制台按字段检索。
        # 同时挂 user_id 与 username，便于按用户过滤/检索。
        "tags": ["openunknown", f"user:{user_id}", f"model:{model}", f"mode:{mode}"],
        "metadata": {
            "session_id": session_id,
            "user_id": user_id,
            "user": username,
            "model": model,
            "mode": mode,
        },
    }
    # 附件：正文以 system 消息注入（不污染用户气泡），附件名以轻量标记追加到用户消息
    # 以便历史回显时仍能看到本轮带过哪些文件。会话标题仍取原始 message，不含附件名。
    attach_msgs, attach_names = _attachment_messages(attachments or [])
    model_message = message
    if attach_names:
        model_message = f"{message}\n\n（已上传附件：{'、'.join(attach_names)}）"
    inputs = {"messages": [*attach_msgs, HumanMessage(content=model_message)]}
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
        store.log_usage(user_id, session_id, model, mode, usage)
        yield sse_event({"usage": usage})
    yield "data: [DONE]\n\n"
