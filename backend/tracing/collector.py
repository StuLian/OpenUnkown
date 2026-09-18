"""trace 采集器：在一轮对话的 graph 执行过程中收集完整原始报文。

collector 通过 config.configurable["trace_collector"] 传给 graph 节点：
- graph 侧负责写入本轮发给模型的原始报文、工具调用与返回、检索结果；
- streaming 侧负责写入最终答案、用量、异常与确认状态；
最后调用 finalize() 统一计算自动标记与耗时，产出可落库的 dict。
"""
from __future__ import annotations

import time
import uuid

from langchain_core.messages import BaseMessage

# 多模态 content 块里的 image_url(data URL) 体积大，落库时用占位符避免 trace 表膨胀
_IMAGE_PLACEHOLDER = "[图片 data URL，已省略]"


def new_run_id() -> str:
    """生成本轮 trace 的唯一 id。"""
    return "run-" + uuid.uuid4().hex


def _content_to_json(content) -> object:
    """把消息 content（str 或块列表）转成可 JSON 序列化的结构。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks: list = []
        for block in content:
            if not isinstance(block, dict):
                blocks.append(str(block))
                continue
            if block.get("type") == "image_url":
                blocks.append({"type": "image_url", "image_url": _IMAGE_PLACEHOLDER})
            else:
                blocks.append(block)
        return blocks
    return str(content)


def message_to_serializable(msg: BaseMessage) -> dict:
    """把 LangChain 消息转成可落库的 dict（id/type/content/name/tool_calls/tool_call_id）。"""
    data: dict = {
        "type": getattr(msg, "type", msg.__class__.__name__),
        "content": _content_to_json(getattr(msg, "content", "")),
    }
    mid = getattr(msg, "id", None)
    if mid:
        data["id"] = mid
    name = getattr(msg, "name", None)
    if name:
        data["name"] = name
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = [
            {
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
            for tc in tool_calls
        ]
    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id:
        data["tool_call_id"] = tool_call_id
    return data


class TraceCollector:
    """一轮对话的 trace 采集器（非线程安全，单轮内串行使用）。"""

    def __init__(
        self,
        user_id: str,
        session_id: str,
        model: str,
        mode: str,
        platform: str,
        input_text: str,
        prompt_version: str = "",
    ):
        self.id = new_run_id()
        self.user_id = user_id
        self.session_id = session_id
        self.model = model
        self.mode = mode
        self.platform = platform
        self.prompt_version = prompt_version
        self.input_text = input_text
        self._started = time.time()

        self.messages: list[dict] = []
        self.tool_calls: list[dict] = []
        self.tool_outputs: list[dict] = []
        self.retrieved_docs: list[dict] = []
        self.answer = ""
        self.usage: dict = {}
        self.error: str | None = None
        self.pending_confirm = False
        self._flags: set[str] = set()

    # ---- graph 侧写入 ----
    def record_llm_input(self, messages: list[BaseMessage]) -> None:
        """记录最后一次提交给模型的完整报文（system + 压缩后的历史，多模态图用占位符）。

        `_chat_node` 每次传入的都是「新建 system 消息 + 完整累计历史」，最后一次调用
        已包含整轮全部报文，故采用覆盖式更新（以最新一次为准）。
        内部按消息 id（tool 消息按 tool_call_id）去重，防御节点因 interrupt/重跑
        而重复调用本方法时产生重复记录。
        """
        seen_ids: set[str] = set()
        seen_tool_ids: set[str] = set()
        result: list[dict] = []
        for msg in messages:
            ser = message_to_serializable(msg)
            if ser.get("type") == "tool":
                key = ser.get("tool_call_id")
                if key and key in seen_tool_ids:
                    continue
                if key:
                    seen_tool_ids.add(key)
            else:
                key = ser.get("id")
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
            result.append(ser)
        self.messages = result

    def record_tool_call(self, tool_call: dict) -> None:
        """记录模型发起的一次工具调用（id/name/args）。"""
        self.tool_calls.append(
            {
                "id": tool_call.get("id", ""),
                "name": tool_call.get("name", ""),
                "args": tool_call.get("args", {}),
            }
        )

    def record_tool_output(self, call_id: str, name: str, output: str) -> None:
        """记录一次工具执行的完整返回（不截断）。"""
        self.tool_outputs.append({"id": call_id, "name": name, "output": str(output)})

    def record_retrieved_docs(self, docs: list[dict]) -> None:
        """记录 RAG 检索的原始结果（含相关度分，供离线分析召回质量）。"""
        self.retrieved_docs = list(docs)

    # ---- streaming 侧写入 ----
    def set_answer(self, text: str) -> None:
        self.answer = text

    def set_usage(self, usage: dict) -> None:
        self.usage = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def set_error(self, err: str) -> None:
        self.error = err

    def set_pending_confirm(self) -> None:
        self.pending_confirm = True

    def add_flag(self, flag: str) -> None:
        self._flags.add(flag)

    # ---- 落库前统一收口 ----
    def finalize(self) -> dict:
        """计算自动标记与耗时，产出可落库的 dict。"""
        if self.error:
            self._flags.add("error")
        if any(o.get("output", "").startswith("Error") for o in self.tool_outputs):
            self._flags.add("tool_error")
        if self.pending_confirm:
            self._flags.add("pending_confirm")
        elif not self.answer.strip():
            self._flags.add("no_answer")

        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "model": self.model,
            "mode": self.mode,
            "platform": self.platform,
            "prompt_version": self.prompt_version,
            "input_text": self.input_text,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "tool_outputs": self.tool_outputs,
            "retrieved_docs": self.retrieved_docs,
            "final_answer": self.answer,
            "usage": self.usage,
            "latency_ms": int((time.time() - self._started) * 1000),
            "error": self.error,
            "flags": sorted(self._flags),
        }
