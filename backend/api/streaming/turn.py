"""单轮图执行的 SSE 事件产出：流式增量、工具调用、confirm、用量、幻觉闸门与落库。

从 streaming.py 拆出（coding.md ≤300 行）；对外由 __init__.py 调用 stream_turn。
"""
from __future__ import annotations

import logging

from fastapi import Request

from backend import store
from backend.agent.grounding import apply_grounding
from backend.agent.memory import schedule_extraction
from backend.api.streaming.confirm import pending_confirm
from backend.config import DEFAULT_PLATFORM, get_platform, mode_enables_thinking

logger = logging.getLogger(__name__)


def _persist_trace(collector) -> None:
    """把一轮 trace 落库；落库失败只告警，不影响主流程。"""
    try:
        store.insert_run(collector.finalize())
    except Exception as e:  # noqa: BLE001
        logger.warning("[trace] 落库失败: %s", e)


async def stream_turn(
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
    confirm = await pending_confirm(graph, config)
    if confirm is not None:
        if collector is not None:
            collector.set_pending_confirm()
        yield {"confirm": confirm}

    if usage:
        store.log_usage(user_id, session_id, model, mode, usage)
        if confirm is None:
            yield {"usage": usage}

    # 幻觉闸门：本轮正常完成时做无据判定 + 降级提示（逻辑与容错见 grounding.apply_grounding）。
    if confirm is None:
        disclaimer = await apply_grounding(collector, answer, config)
        if disclaimer:
            yield {"delta": disclaimer}

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
