"""SSE 流式回答的公共逻辑：消息打包、消息转字典、流式生成。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Request
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from backend import store
from backend.agent.graph import extract_image_urls, extract_text_content, get_graph
from backend.auth.service import resolve_api_key
from backend.config import DEFAULT_PLATFORM, VISION_MODEL, mode_enables_thinking
from backend.files.image import ocr_image
from backend.files.parser import MAX_CONTENT_CHARS

logger = logging.getLogger(__name__)


def sse_event(payload: dict) -> str:
    """把数据打包成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def message_to_dict(m) -> dict | None:
    """把 LangChain 消息对象转成前端可用的 {role, content, usage?, images?}。

    工具调用相关的中间消息不展示：tool 消息、以及仅包含 tool_calls 没有正文的 assistant 消息。
    assistant 消息若携带 usage_metadata，则附上 token 用量，供前端刷新后仍能展示。
    多模态消息中的图片单独提取为 images 数组，供前端在气泡里渲染。
    """
    if m.type in ("system", "tool"):
        return None
    content = extract_text_content(m.content, mark_images=False)
    if m.type == "ai" and getattr(m, "tool_calls", None) and not content.strip():
        return None
    role = {"human": "user", "ai": "assistant"}.get(m.type, m.type)
    images = extract_image_urls(m.content)
    if role not in ("user", "assistant") or (not content and not images):
        return None
    result = {"role": role, "content": content}
    if images:
        result["images"] = images
    attach_names = (getattr(m, "additional_kwargs", None) or {}).get("attachment_names") or []
    if attach_names:
        result["attachments"] = attach_names
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


def _split_attachments(attachments: list) -> tuple[list[SystemMessage], list[tuple[str, str]], list[str]]:
    """把附件拆成三类，返回 (文本系统消息列表, 图片列表[(文件名, data_url)], 附件名列表)。

    - 文本附件 → SystemMessage（正文不进入用户气泡，历史回显时被过滤）；
    - 图片附件 → 只收集 data URL，OCR 延迟到发送时（见 stream_answer）再执行。
    """
    text_msgs: list[SystemMessage] = []
    images: list[tuple[str, str]] = []
    names: list[str] = []
    for i, att in enumerate(attachments, 1):
        file_type = (getattr(att, "file_type", None) or "text")
        filename = (getattr(att, "filename", None) or "未命名文件")
        names.append(filename)

        if file_type == "image":
            data_url = getattr(att, "image", None) or ""
            if data_url:
                images.append((filename, data_url))
        else:
            content = getattr(att, "content", None) or ""
            # 后端兜底截断，防止绕过前端直接提交超长内容
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS] + "\n...[内容过长已截断]"
            text_msgs.append(
                SystemMessage(
                    content=(
                        f"[附件 {i}] 用户上传了文件《{filename}》，其解析后的纯文本内容如下，"
                        f"请结合这些内容回答用户问题：\n\n{content}"
                    )
                )
            )
    return text_msgs, images, names


def _build_config(
    user_id: str,
    session_id: str,
    model: str,
    mode: str,
    api_key: str,
    username: str,
) -> dict:
    """组装 LangGraph 运行配置（/chat 与 /chat/confirm 共用）。"""
    return {
        "configurable": {
            "thread_id": store.thread_id_for(user_id, session_id),
            "model": model,
            "mode": mode,
            "platform": DEFAULT_PLATFORM,
            "api_key": api_key,
            "user_id": user_id,
        },
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
    """若图停在飞书写操作待确认的 interrupt 上，返回其负载；否则返回 None。"""
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
            if isinstance(val, dict) and val.get("type") == "lark_write_confirmation":
                return {
                    "command": val.get("command", ""),
                    "risk": val.get("risk", ""),
                    "tool_call_id": val.get("tool_call_id", ""),
                }
    return None


async def _drain_pending_confirm(graph, config: dict, request: Request) -> bool:
    """若该会话残留未确认的飞书写操作（用户刷新/切换会话后重发），先自动取消并跑完。

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
        logger.warning("清理残留飞书确认失败: %s", e)
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

    飞书写操作在 tools 节点被 interrupt 停住时，产出 confirm 事件且不产 usage；
    整轮正常结束时产出 usage（并落 usage_log）。
    """
    usage = None
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
                yield {"delta": text}
    except Exception as exc:  # noqa: BLE001
        yield {"error": str(exc)}

    # 图若停在飞书写操作待确认处，产出 confirm 事件；此时轮次未完成，不产 usage。
    confirm = await _pending_confirm(graph, config)
    if confirm is not None:
        yield {"confirm": confirm}

    if usage:
        store.log_usage(user_id, session_id, model, mode, usage)
        if confirm is None:
            yield {"usage": usage}


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

    # 附件：文本正文以 system 消息注入；图片收集 data URL。
    # OCR 延迟到此刻（用户已真正发送）才执行，避免上传时无谓调用模型。
    text_msgs, images, attach_names = _split_attachments(attachments or [])
    attach_msgs: list[SystemMessage] = list(text_msgs)
    image_urls = [url for _, url in images]

    if images:
        ocr_results = await asyncio.gather(
            *(ocr_image(url, api_key) for _, url in images),
            return_exceptions=True,
        )
        for (img_name, _), result in zip(images, ocr_results):
            if isinstance(result, BaseException):
                logger.warning("图片 OCR 失败 %s: %s", img_name, result)
                continue
            if result:
                attach_msgs.append(
                    SystemMessage(
                        content=(
                            f"[图片] 图片《{img_name}》经 OCR 提取的文字如下，"
                            f"请结合图片与这段文字回答用户问题：\n\n{result}"
                        )
                    )
                )

    # 图片附件需要多模态模型：切换视觉模型，并关闭思考（多数视觉模型不支持 enable_thinking）
    effective_model = model
    effective_mode = mode
    if image_urls:
        effective_model = VISION_MODEL
        effective_mode = "fast"

    graph = await get_graph()
    config = _build_config(user_id, session_id, effective_model, effective_mode, api_key, username)

    # 上一轮若残留未确认的飞书写操作（用户中途刷新/切换会话），先自动取消，避免阻塞本轮
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
    """飞书写操作人工确认后，从 checkpoint 恢复图并继续流式输出剩余回答。

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
    config = _build_config(user_id, session_id, model, mode, api_key, username)

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
