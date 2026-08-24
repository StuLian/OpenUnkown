"""应用全局配置。"""
from __future__ import annotations

from functools import lru_cache

from dashscope.common.api_key import get_default_api_key


# DashScope 的 OpenAI 兼容接入地址，配合 langchain-openai 使用
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 可选模型列表（DashScope 通义千问系列），前端选择器与后端校验共用
AVAILABLE_MODELS = [
    {"id": "qwen3.7-plus", "name": "Qwen3.7 Plus（新款均衡）"},
    {"id": "qwen-max", "name": "Qwen Max（旗舰顶配）"},
    {"id": "qwen-plus", "name": "Qwen Plus（老版均衡）"},
    {"id": "qwen-turbo", "name": "Qwen Turbo（高速轻量）"},
    {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro（旗舰顶配）"},
    {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash（高速轻量）"},
    {"id": "deepseek-v3", "name": "DeepSeek V3（老版均衡）"},
    {"id": "deepseek-r1", "name": "DeepSeek R1（高速轻量）"},
    {"id": "glm-5", "name": "GLM-5（高速轻量）"},
]

# 默认模型
DEFAULT_MODEL = "qwen3.7-plus"

# 兼容旧引用：默认模型名称
MODEL_NAME = DEFAULT_MODEL

# 应用名称
APP_NAME = "OpenUnknown"

_MODEL_IDS = {m["id"] for m in AVAILABLE_MODELS}


def is_valid_model(model_id: str) -> bool:
    """校验模型 id 是否在可选列表内。"""
    return model_id in _MODEL_IDS


@lru_cache(maxsize=1)
def get_api_key() -> str:
    """获取 DashScope ApiKey，按用户要求通过 get_default_api_key 读取。"""
    api_key = get_default_api_key()
    if not api_key:
        raise RuntimeError(
            "未获取到 DashScope ApiKey，请先配置 ~/.dashscope/api_key 或环境变量 DASHSCOPE_API_KEY"
        )
    return api_key
