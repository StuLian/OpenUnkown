"""幻觉闸门：生成后 grounding 判定（无据不答）。

设计见 context/version/20260923-111235-hallucination-gate/proposal.md：
- 触发：仅当本轮「无工具调用 + 无 RAG 召回 + 无记忆注入」时才判定（省成本，只对高风险场景付费）。
- 判定：拿「用户问题 + 助手回答 + 证据(可能为空)」问一次便宜模型，输出结构化 verdict。
- 降级：grounded=false 且 confidence ≥ 阈值 → 打 hallucination_risk + 追加免责提示（标注不拒答）。
- 容错：判定异常 / JSON 解析失败一律按「不拦截」处理，绝不阻塞主流程。

本模块只做「纯判定 + 解析」，不直接碰 trace 落库与流式收口（由 streaming.py 调用）。
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

# 追加在正文之后、仅当判定为无据时下发的免责提示（markdown 引用块）
GROUNDING_DISCLAIMER = "\n\n> ⚠️ 以上回答基于模型自身知识、未经检索 / 工具验证，请谨慎采信。"


def should_run_grounding(has_tool_calls: bool, has_retrieved_docs: bool) -> bool:
    """是否触发判定：本轮无工具调用、无 RAG 召回时才判。

    记忆注入**不算**「有证据」——记忆是用户画像/偏好，不支撑具体事实断言；
    若因记忆注入就跳过，闸门会因「几乎每轮都有记忆」而形同虚设（2026-09-23 修复）。
    有工具/RAG 的回答零额外成本；证据内的误读属二期范围。
    """
    return not has_tool_calls and not has_retrieved_docs


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
    """对完成的一轮回答做无据判定；返回要追加的免责提示（None 表示无需/失败）。

    触发条件（无工具调用 + 无 RAG 召回 + 无记忆注入）不满足、判定失败、解析失败
    都返回 None，绝不影响主流程。collector 传 None 或未启用时直接返回 None。
    """
    if not GROUNDING_ENABLED or collector is None or not answer.strip():
        return None
    if not should_run_grounding(
        has_tool_calls=bool(collector.tool_calls),
        has_retrieved_docs=bool(collector.retrieved_docs),
    ):
        return None
    cfg = config.get("configurable") or {}
    evidence = build_evidence_text(collector.tool_outputs, collector.retrieved_docs)
    memory_text = _extract_memory_text(collector)
    if memory_text:
        evidence = f"{evidence}\n\n{memory_text}".strip() if evidence else memory_text
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
