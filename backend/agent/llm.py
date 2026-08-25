"""通义千问 / DeepSeek 模型封装。

思考模式通过 DashScope 兼容接口的 enable_thinking 参数开启深度推理，
模型会先输出 reasoning_content（思维链），再输出 content（最终答案）。
langchain-openai 0.2.14 的流式转换会丢弃 reasoning_content，
这里用 ThinkingChatOpenAI 子类把它保留到 additional_kwargs，供上层流式推送。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, AsyncIterator, Iterator, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import AIMessageChunk, BaseMessage, BaseMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _create_usage_metadata,
)

from backend.config import DASHSCOPE_BASE_URL, DEFAULT_MODEL, get_api_key


def _convert_chunk_with_reasoning(
    chunk: dict,
    default_class: Type[BaseMessageChunk],
    base_generation_info: Optional[dict],
) -> Optional[ChatGenerationChunk]:
    """复制 langchain-openai 的流式 chunk 转换，并额外保留 reasoning_content。

    reasoning_content 是 DashScope 思考模式下随每个 delta 返回的思维链增量，
    原生转换函数只映射 content / tool_calls 等字段，会把思维链丢掉。
    """
    token_usage = chunk.get("usage")
    choices = chunk.get("choices", [])
    usage_metadata = _create_usage_metadata(token_usage) if token_usage else None
    if len(choices) == 0:
        return ChatGenerationChunk(
            message=default_class(content="", usage_metadata=usage_metadata)
        )
    choice = choices[0]
    if choice["delta"] is None:
        return None

    message_chunk = _convert_delta_to_message_chunk(choice["delta"], default_class)
    reasoning = choice["delta"].get("reasoning_content")
    if reasoning is not None and isinstance(message_chunk, AIMessageChunk):
        message_chunk.additional_kwargs["reasoning_content"] = reasoning

    generation_info = {**base_generation_info} if base_generation_info else {}
    if finish_reason := choice.get("finish_reason"):
        generation_info["finish_reason"] = finish_reason
        if model_name := chunk.get("model"):
            generation_info["model_name"] = model_name
        if system_fingerprint := chunk.get("system_fingerprint"):
            generation_info["system_fingerprint"] = system_fingerprint
    if logprobs := choice.get("logprobs"):
        generation_info["logprobs"] = logprobs
    if usage_metadata and isinstance(message_chunk, AIMessageChunk):
        message_chunk.usage_metadata = usage_metadata

    return ChatGenerationChunk(
        message=message_chunk, generation_info=generation_info or None
    )


class ThinkingChatOpenAI(ChatOpenAI):
    """保留 reasoning_content 的 ChatOpenAI 子类。

    在思考模式下，DashScope 的流式响应每个 delta 会带 reasoning_content 字段，
    这里重写 _stream / _astream，让这些思维链增量进入 chunk 的 additional_kwargs。
    """

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info = {}
        response = self.client.create(**payload)
        with response:
            is_first_chunk = True
            for chunk in response:
                if not isinstance(chunk, dict):
                    chunk = chunk.model_dump()
                generation_chunk = _convert_chunk_with_reasoning(
                    chunk,
                    default_chunk_class,
                    base_generation_info if is_first_chunk else {},
                )
                if generation_chunk is None:
                    continue
                default_chunk_class = generation_chunk.message.__class__
                logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                if run_manager:
                    run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk, logprobs=logprobs
                    )
                is_first_chunk = False
                yield generation_chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        kwargs["stream"] = True
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        default_chunk_class: Type[BaseMessageChunk] = AIMessageChunk
        base_generation_info = {}
        response = await self.async_client.create(**payload)
        async with response:
            is_first_chunk = True
            async for chunk in response:
                if not isinstance(chunk, dict):
                    chunk = chunk.model_dump()
                generation_chunk = _convert_chunk_with_reasoning(
                    chunk,
                    default_chunk_class,
                    base_generation_info if is_first_chunk else {},
                )
                if generation_chunk is None:
                    continue
                default_chunk_class = generation_chunk.message.__class__
                logprobs = (generation_chunk.generation_info or {}).get("logprobs")
                if run_manager:
                    await run_manager.on_llm_new_token(
                        generation_chunk.text, chunk=generation_chunk, logprobs=logprobs
                    )
                is_first_chunk = False
                yield generation_chunk


@lru_cache(maxsize=16)
def get_llm(model_name: str = DEFAULT_MODEL, enable_thinking: bool = False) -> ThinkingChatOpenAI:
    """按模型名 + 思考开关构建聊天模型，走 DashScope 的 OpenAI 兼容协议。

    按 (model_name, enable_thinking) 缓存，切换模型或模式时复用已构建实例。
    """
    return ThinkingChatOpenAI(
        model=model_name,
        api_key=get_api_key(),
        base_url=DASHSCOPE_BASE_URL,
        temperature=0.7,
        streaming=True,
        stream_usage=True,
        extra_body={"enable_thinking": True} if enable_thinking else None,
    )
