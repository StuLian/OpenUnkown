"""通义千问模型封装。"""
from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from backend.config import DASHSCOPE_BASE_URL, DEFAULT_MODEL, get_api_key


@lru_cache(maxsize=8)
def get_llm(model_name: str = DEFAULT_MODEL) -> ChatOpenAI:
    """按模型名构建聊天模型，走 DashScope 的 OpenAI 兼容协议。

    按 model_name 缓存，切换模型时复用已构建的实例。
    """
    return ChatOpenAI(
        model=model_name,
        api_key=get_api_key(),
        base_url=DASHSCOPE_BASE_URL,
        temperature=0.7,
        streaming=True,
        stream_usage=True,
    )
