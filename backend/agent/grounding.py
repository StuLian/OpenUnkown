"""幻觉闸门：生成后 grounding 判定（无据不答 + 有据校验）。

v1 见 context/version/20260923-111235-hallucination-gate/proposal.md，二期见
context/version/20260923-154738-hallucination-evidence/proposal.md：
- 触发：答案非空即判（二期放宽，不再只判「无工具 + 无 RAG」）。
- 判定：拿「用户问题 + 助手回答 + 证据(工具返回+RAG召回+记忆，可能为空)」问一次便宜模型。
- 降级：grounded=false 且 confidence ≥ 阈值 → 打 hallucination_risk + 追加免责提示（标注不拒答）。
- 容错：判定异常 / JSON 解析失败一律按「不拦截」处理，绝不阻塞主流程。

本模块只做「纯判定 + 解析」，不直接碰 trace 落库与流式收口（由 streaming.turn 调用）。
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import SystemMessage

from backend.agent.llm import get_llm
from backend.agent.prompts import GROUNDING_PROMPT
from backend.config import (
    DEFAULT_PLATFORM,
    GROUNDING_CONFIDENCE_THRESHOLD,
    GROUNDING_ENABLED,
    GROUNDING_MODEL,
    get_platform,
)

logger = logging.getLogger(__name__)

# 追加在正文之后、仅当判定为无据/与证据不符时下发的免责提示（markdown 引用块）
GROUNDING_DISCLAIMER = "\n\n> ⚠️ 以上回答可能存在事实性错误，请谨慎采信。"

# 判定证据最大长度：工具返回 / RAG 召回可能很长（如 shell 输出 20KB），超限截断防顶破预算
EVIDENCE_MAX_CHARS = 6000


def _truncate(text: str, max_chars: int) -> str:
    """把证据文本截断到 max_chars：保头保尾、砍中间。

    关键事实常在证据末尾（最近的工具返回），只保头部会把末尾事实砍掉、造成误伤；
    故保留前 2/3 + 后 1/3，中间省略（2026-09-23 二期验证修复）。
    """
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n...(中间省略 {omitted} 字)...\n" + text[-tail:]


def _extract_memory_text(collector) -> str:
    """从 collector.messages 里取出 kind=memory 的注入记忆文本，作为判定证据。"""
    for m in getattr(collector, "messages", None) or []:
        if isinstance(m, dict) and m.get("kind") == "memory":
            return str(m.get("content", ""))
    return ""


def should_warn(verdict: dict) -> bool:
    """根据判定结果决定是否降级提示 + 打标。

    grounded=false 且判定置信度足够高才 warn；置信度低时「宁漏不误伤」。
    """
    if verdict.get("grounded") is not False:
        return False
    confidence = verdict.get("confidence")
    if not isinstance(confidence, (int, float)):
        return False
    return float(confidence) >= GROUNDING_CONFIDENCE_THRESHOLD


def build_evidence_text(tool_outputs: list[dict], retrieved_docs: list[dict]) -> str:
    """把本轮工具返回 + RAG 召回拼成判定用证据文本（可能为空串）。"""
    parts: list[str] = []
    for o in tool_outputs or []:
        name = o.get("name") or "工具"
        parts.append(f"[工具 {name}]\n{o.get('output') or ''}")
    for d in retrieved_docs or []:
        parts.append(str(d))
    return "\n\n".join(parts)


def parse_verdict(text: str) -> dict | None:
    """解析判定模型返回的 JSON；任何解析失败返回 None（= 不拦截）。

    容错：剥掉 ```json 围栏、截取首尾大括号、缺省字段给安全默认值；
    但 grounded 必须是 bool，否则整个判定作废（宁漏不误伤）。
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("grounded"), bool):
        return None
    confidence = obj.get("confidence")
    obj["confidence"] = float(confidence) if isinstance(confidence, (int, float)) else 0.0
    spans = obj.get("ungrounded_spans")
    obj["ungrounded_spans"] = spans if isinstance(spans, list) else []
    obj["reason"] = obj.get("reason") if isinstance(obj.get("reason"), str) else ""
    return obj


async def check_grounding(
    query: str,
    answer: str,
    evidence: str,
    api_key: str,
    base_url: str,
) -> dict | None:
    """对最终回答做一次 grounding 判定；失败返回 None（调用方按不拦截处理）。"""
    if not api_key or not query.strip() or not answer.strip():
        return None
    prompt = GROUNDING_PROMPT.format(
        evidence=evidence or "（无）", query=query, answer=answer
    )
    try:
        llm = get_llm(
            GROUNDING_MODEL, enable_thinking=False, api_key=api_key, base_url=base_url
        )
        resp = await llm.ainvoke([SystemMessage(content=prompt)])
    except Exception as e:  # noqa: BLE001
        logger.warning("[幻觉闸门] 判定模型调用失败，按不拦截处理: %s", e)
        return None
    content = getattr(resp, "content", "")
    if isinstance(content, list):  # 多模态块列表时只取文本块
        content = " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    verdict = parse_verdict(str(content))
    if verdict is None:
        logger.warning("[幻觉闸门] 判定输出解析失败，按不拦截处理")
    return verdict


async def apply_grounding(collector, answer: str, config: dict) -> str | None:
    """对完成的一轮回答做 grounding 判定；返回要追加的免责提示（None 表示无需/失败）。

    二期：答案非空即判（不再只判「无据」），把真实证据（工具返回 + RAG 召回 + 记忆）
    传给判定模型，核对「回答是否忠于证据」。判定失败/解析失败都返回 None，绝不影响主流程。
    """
    if not GROUNDING_ENABLED or collector is None or not answer.strip():
        return None
    cfg = config.get("configurable") or {}
    evidence = _truncate(
        build_evidence_text(collector.tool_outputs, collector.retrieved_docs),
        EVIDENCE_MAX_CHARS,
    )
    memory_text = _extract_memory_text(collector)
    if memory_text:
        merged = f"{evidence}\n\n{memory_text}".strip() if evidence else memory_text
        evidence = _truncate(merged, EVIDENCE_MAX_CHARS)
    verdict = await check_grounding(
        query=collector.input_text,
        answer=answer,
        evidence=evidence,
        api_key=cfg.get("api_key") or "",
        base_url=get_platform(cfg.get("platform") or DEFAULT_PLATFORM)["base_url"],
    )
    if verdict is None:
        return None
    collector.set_grounding(verdict)
    if should_warn(verdict):
        collector.add_flag("hallucination_risk")
        return GROUNDING_DISCLAIMER
    return None
