"""上下文组装：消息工具、历史压缩，以及本轮发给模型的 messages 组装（含记忆注入）。

从 graph.py 拆出，避免其继续膨胀（coding.md ≤300 行）；Phase 2 的记忆注入（滚动摘要 +
长记忆召回）也集中在此，graph 只负责调用。
"""
from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage, ToolMessage

from backend.agent.memory import (
    MEMORY_KIND,
    SUMMARY_KEEP_TAIL,
    build_memory_text,
    message_text,
    recall_facts,
    should_summarize,
    summarize_history,
)
from backend.store.memory import load_summary, save_summary

logger = logging.getLogger(__name__)

# 发给模型时：尾部消息保持原文（覆盖当前工具轮），更早的超长工具结果截断。
# 不改 checkpoint，只压缩本轮 LLM 输入。
KEEP_TAIL = 16
OLD_TOOL_CHARS = 240

# 工具调用次数达上限后追加的强制作答指令
FORCE_ANSWER_TEXT = (
    "已连续调用多次工具仍未得到最终答案。现在必须停止调用工具，"
    "直接基于已获取的信息给出最终回答，不要再次调用任何工具。"
)


def extract_text_content(content, mark_images: bool = True) -> str:
    """从消息内容（str 或多模态块列表）提取纯文本。

    多模态 HumanMessage 的 content 是 [{type:text,text:...}, {type:image_url,...}]
    这样的块列表，直接 str() 会带出超长 base64，这里只保留文本部分。
    mark_images=True 时图片块用「[图片]」占位（用于意图识别/日志/字数统计）；
    用于界面回显时可传 False，避免和真正渲染出来的图片重复。
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "image_url":
            if mark_images:
                parts.append("[图片]")
        else:
            parts.append(str(block))
    return " ".join(parts)


def extract_image_urls(content) -> list[str]:
    """从多模态消息内容中提取所有图片 URL（data URL 或 http(s)）。"""
    if isinstance(content, str):
        return []
    urls: list[str] = []
    for block in content or []:
        if not isinstance(block, dict) or block.get("type") != "image_url":
            continue
        image_url = block.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url", "")
        else:
            url = image_url
        if isinstance(url, str) and url:
            urls.append(url)
    return urls


def compact_history(messages: list) -> list:
    """压缩历史中的旧工具原文，避免长对话每轮把全部工具返回再送给模型。"""
    if len(messages) <= KEEP_TAIL:
        return list(messages)

    head, tail = messages[:-KEEP_TAIL], messages[-KEEP_TAIL:]
    compacted = []
    for msg in head:
        if getattr(msg, "type", None) != "tool":
            compacted.append(msg)
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if len(content) <= OLD_TOOL_CHARS:
            compacted.append(msg)
            continue
        compacted.append(ToolMessage(
            content=content[:OLD_TOOL_CHARS] + f"\n...(已截断，原文 {len(content)} 字)",
            tool_call_id=msg.tool_call_id,
            name=getattr(msg, "name", None),
        ))
    return compacted + list(tail)


def messages_chars(messages: list) -> int:
    """粗算消息文本总字数，便于日志对比压缩效果。"""
    return sum(len(extract_text_content(getattr(m, "content", ""))) for m in messages)


def log_llm_input(model_name: str, messages: list, tool_names: list[str]) -> None:
    """把本轮发给大模型的提示词打印到服务日志，方便核对。"""
    lines = [
        "",
        "=" * 72,
        f"[LLM 输入] 模型={model_name}  消息数={len(messages)}  "
        f"约 {messages_chars(messages)} 字  绑定工具={tool_names}",
        "=" * 72,
    ]
    for i, msg in enumerate(messages):
        role = getattr(msg, "type", msg.__class__.__name__)
        name = getattr(msg, "name", None) or ""
        content = extract_text_content(getattr(msg, "content", ""))
        lines.append(f"[{i}] {role}" + (f" ({name})" if name else ""))
        lines.append(content if content else "(空)")
        if getattr(msg, "tool_calls", None):
            lines.append(f"  tool_calls: {msg.tool_calls}")
        lines.append("-" * 40)
    lines.append("=" * 72)
    text = "\n".join(lines)
    logger.info(text)
    print(text, flush=True)


async def assemble_model_messages(
    *,
    state_messages: list,
    system_prompt: str,
    identity_text: str,
    user_id: str,
    session_id: str,
    query: str,
    api_key: str,
    base_url: str,
    force_answer: bool,
) -> tuple[list, dict]:
    """组装本轮发给模型的 messages（逻辑结构，含记忆注入）。

    Returns:
        (messages, info)：info 含 memory_injected / summarized 两个布尔标记。
    任何一步失败都降级为「不注入 / 不摘要」，绝不阻塞主流程。
    """
    info = {"memory_injected": False, "summarized": False}
    all_messages = list(state_messages)

    # 1) 工作记忆：读取已有摘要；超预算时滚动生成新摘要（失败降级为不摘要）
    summary = ""
    try:
        if session_id:
            summary = load_summary(user_id, session_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[记忆] 读取摘要失败: %s", e)

    # 仅当「确有老消息可压缩」时才摘要：条数不超过保留窗口时 old 为空，
    # 此时摘要只会伪造成一段无依据的文本并反复注入（R3 修复）。
    if should_summarize(all_messages) and len(all_messages) > SUMMARY_KEEP_TAIL:
        old = all_messages[:-SUMMARY_KEEP_TAIL]
        recent = all_messages[-SUMMARY_KEEP_TAIL:]
        try:
            new_summary = await summarize_history(old, summary, api_key, base_url)
            if new_summary:
                summary = new_summary
                if session_id:
                    save_summary(user_id, session_id, new_summary)
                info["summarized"] = True
                all_messages = recent  # 老消息已被摘要覆盖
        except Exception as e:  # noqa: BLE001
            logger.warning("[记忆] 摘要失败，回退为不摘要: %s", e)

    history = compact_history(all_messages)

    # 2) 长记忆：按 query 召回。recall_facts 内部已兜底，这里再兜一层，
    #    确保任何意外异常都不会冒泡打断本轮回答（R1 修复）。
    facts: list[str] = []
    try:
        facts = await recall_facts(user_id, query, api_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("[记忆] 召回异常，跳过记忆注入: %s", e)

    messages: list = [SystemMessage(content=f"{system_prompt}\n\n{identity_text}")]
    memory_text = build_memory_text(summary, facts)
    if memory_text:
        messages.append(
            SystemMessage(content=memory_text, additional_kwargs={"kind": MEMORY_KIND})
        )
        info["memory_injected"] = True
    messages.extend(history)
    if force_answer:
        messages.append(SystemMessage(content=FORCE_ANSWER_TEXT))

    logger.info(
        "[记忆] 历史 %d 字 -> %d 字；摘要=%s；召回记忆 %d 条；原历史 %d 条 -> %d 条",
        sum(len(message_text(m)) for m in state_messages),
        messages_chars(messages),
        info["summarized"],
        len(facts),
        len(state_messages),
        len(messages),
    )
    return messages, info
