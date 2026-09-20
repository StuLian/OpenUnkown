"""记忆编排：工作记忆（token 预算 + 滚动摘要）与可检索长记忆（抽取 + 召回）。

设计见 context/version/20260918-175408-memory-phase2/proposal.md：
- 工作记忆：历史总字数超 MAX_HISTORY_CHARS 时，把保留窗口外的老消息 + 已有摘要
  交便宜模型滚成新摘要，存 memories.summary；窗口内消息仍按紧凑规则截断工具原文。
- 长记忆：每轮结束异步抽取用户事实/偏好，向量化存 memories.fact；下一轮按 query
  向量余弦召回 top-k，作为独立 SystemMessage（kind=memory）注入。

阈值常量集中在文件顶部，便于一处调整。所有失败都降级：记忆是增强，绝不阻塞主流程。
"""
from __future__ import annotations

import asyncio
import logging
import re

import numpy as np
from langchain_core.messages import SystemMessage

from backend.agent.llm import get_llm
from backend.agent.prompts import MEMORY_EXTRACT_PROMPT, MEMORY_SUMMARY_PROMPT
from backend.rag.embeddings import embed_texts
from backend.store.memory import add_fact, count_facts, delete_fact, list_facts

logger = logging.getLogger(__name__)

# ---- 可调常量（集中在此，一处可改）----
MAX_HISTORY_CHARS = 12000   # 触发滚动摘要的历史字数预算
SUMMARY_KEEP_TAIL = 16      # 摘要时保留的最近消息条数（与 context.KEEP_TAIL 对齐）
MEMORY_TOP_K = 3            # 每轮召回的相关记忆条数
MEMORY_MAX_FACTS = 50       # 单用户长记忆条数上限
MEMORY_MODEL = "qwen-turbo"  # 摘要 / 抽取用的便宜模型
MEMORY_MIN_SIM = 0.35       # 召回最低余弦相似度（保守默认，待真实数据校准）
FACT_DEDUP_SIM = 0.92       # 事实去重阈值：与已有记忆相似度高于此则跳过

MEMORY_KIND = "memory"      # 记忆消息的 kind 标记（供 trace 显示 memory tag）

# 后台任务引用集合：防止 fire-and-forget 任务被垃圾回收
_background: set = set()


def message_text(msg) -> str:
    """取一条消息的纯文本内容。

    多模态块列表只取文本块、图片块记为「[图片]」占位——绝不能把 image_url 里的
    base64 算进来，否则带图轮次会被误判为超预算而触发摘要（R2 修复）。
    """
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif block.get("type") == "image_url":
                parts.append("[图片]")
            else:
                parts.append(str(block))
        return " ".join(parts)
    return str(content)


def history_chars(messages: list) -> int:
    """粗算消息列表总字数（中文按字计，够用于预算判断）。"""
    return sum(len(message_text(m)) for m in messages)


def should_summarize(messages: list) -> bool:
    """历史是否超过字数预算、需要滚动摘要。"""
    return history_chars(messages) > MAX_HISTORY_CHARS


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """两个向量的余弦相似度（含零向量保护）。"""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(a @ b) / (na * nb)


async def summarize_history(
    old_messages: list, existing_summary: str, api_key: str, base_url: str
) -> str:
    """把老消息 + 已有摘要滚成新摘要（失败抛异常，由调用方降级）。"""
    transcript = "\n".join(
        f"{getattr(m, 'type', '?')}: {message_text(m)[:400]}" for m in old_messages
    )
    prompt = MEMORY_SUMMARY_PROMPT.format(
        existing=existing_summary or "（无）", transcript=transcript
    )
    llm = get_llm(MEMORY_MODEL, enable_thinking=False, api_key=api_key, base_url=base_url)
    resp = await llm.ainvoke([SystemMessage(content=prompt)])
    return message_text(resp).strip()


async def recall_facts(user_id: str, query: str, api_key: str) -> list[str]:
    """按 query 语义召回 top-k 事实记忆（失败返回空，不注入）。

    整段包在 try 内：读取/向量化/排序任一步异常都降级为「不注入」，
    绝不让记忆失败冒泡影响本轮回答（R1 修复）。
    """
    if not user_id or not query.strip():
        return []
    try:
        facts = [f for f in list_facts(user_id) if f.get("embedding")]
        if not facts:
            return []
        vectors = await asyncio.to_thread(embed_texts, [query], "query", api_key)
        if not vectors:
            logger.warning("[记忆] 召回向量为空，跳过记忆注入")
            return []
        query_vec = np.array(vectors[0], dtype="float32")
        ranked = sorted(
            (
                (_cosine(query_vec, np.array(f["embedding"], dtype="float32")), f["content"])
                for f in facts
            ),
            key=lambda x: -x[0],
        )
        return [
            content
            for score, content in ranked[:MEMORY_TOP_K]
            if score >= MEMORY_MIN_SIM
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("[记忆] 召回失败，跳过记忆注入: %s", e)
        return []


def build_memory_text(summary: str, facts: list[str]) -> str:
    """把召回的 facts 与滚动摘要拼成注入用的记忆文本（都为空则返回空串）。"""
    parts: list[str] = []
    if facts:
        parts.append("## 相关记忆\n" + "\n".join(f"- {f}" for f in facts))
    if summary:
        parts.append("## 历史对话摘要\n" + summary)
    return "\n\n".join(parts)


# 事实行首的列表标记，**必须后跟空白**才算标记：
#   "- 条目" / "* 条目" / "1. 条目" / "2) 条目" / "3、条目"  -> 剥掉标记
#   "3.14是圆周率" / "-5度以下" / "2、3线城市" / "2024年搬到北京" -> 原样保留正文
# 用「标记 + 空白」而非单纯「标记」，避免把正文里的数字/负号/小数当成序号（R4/N1）
_FACT_PREFIX_RE = re.compile(r"^\s*(?:[-•*]+\s+|\d+[.、)]\s+)")


def parse_facts(text: str) -> list[str]:
    """解析抽取结果：每行一条，只去掉行首列表标记与空行，过滤过长项。

    用正则精确匹配「列表标记」，不能按字符集 lstrip——那会把正文数字吃掉
    （如「2024年搬到北京」被剥成「年搬到北京」，R4 修复）。
    """
    out: list[str] = []
    for line in text.splitlines():
        item = _FACT_PREFIX_RE.sub("", line).strip()
        if item and len(item) <= 200:
            out.append(item)
    return out


async def extract_facts(
    user_id: str, user_text: str, answer: str, api_key: str, base_url: str
) -> None:
    """从一轮对话抽取用户事实并入库（含去重与上限裁剪），失败静默。"""
    if not user_id or not user_text.strip() or not answer.strip():
        return
    try:
        llm = get_llm(MEMORY_MODEL, enable_thinking=False, api_key=api_key, base_url=base_url)
        prompt = MEMORY_EXTRACT_PROMPT.format(
            user=user_text[:1500], assistant=answer[:1500]
        )
        resp = await llm.ainvoke([SystemMessage(content=prompt)])
        new_facts = parse_facts(message_text(resp))
        if not new_facts:
            return

        existing = [f for f in list_facts(user_id) if f.get("embedding")]
        existing_vecs = [np.array(f["embedding"], dtype="float32") for f in existing]

        vectors = await asyncio.to_thread(embed_texts, new_facts, "document", api_key)
        for content, vector in zip(new_facts, vectors):
            vec = np.array(vector, dtype="float32")
            if any(_cosine(vec, ev) >= FACT_DEDUP_SIM for ev in existing_vecs):
                continue
            add_fact(user_id, content, [float(x) for x in vec])
            existing_vecs.append(vec)
            logger.info("[记忆] 新增事实: %s", content)
        _evict_overflow(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[记忆] 事实抽取失败（忽略）: %s", e)


def _evict_overflow(user_id: str) -> None:
    """事实记忆超过 MEMORY_MAX_FACTS 时，删除最旧的若干条。"""
    overflow = count_facts(user_id) - MEMORY_MAX_FACTS
    if overflow <= 0:
        return
    for fact in list_facts(user_id)[-overflow:]:
        delete_fact(fact["id"])


def schedule_extraction(
    user_id: str, user_text: str, answer: str, api_key: str, base_url: str
) -> None:
    """把长记忆抽取放到后台执行（fire-and-forget，不阻塞、不抛错）。"""
    if not api_key or not answer.strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 无运行中的事件循环（如同步脚本）时跳过
        return
    # 先取到运行中的 loop 再创建协程：避免 create_task 失败时留下未被 await 的协程（R8）
    task = loop.create_task(extract_facts(user_id, user_text, answer, api_key, base_url))
    _background.add(task)
    task.add_done_callback(_background.discard)
