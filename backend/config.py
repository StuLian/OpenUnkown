"""应用全局配置。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 尽早加载项目根目录的 .env（backend/ 的上一级），
# 使 LangSmith 等环境变量配置无需手动 export 即可生效。
# 注意：必须放在任何会读取环境变量的第三方库 import 之前（例如 dashscope 在 import
# 时会固化 api_key），否则 .env 中的配置无法被这些库感知。
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


# 支持的模型服务平台。默认走百炼（阿里云 DashScope），日后可在此扩展其他平台。
# 每个平台给出 OpenAI 兼容接入地址、连通性测试用的轻量模型。
PLATFORMS = [
    {
        "id": "bailian",
        "name": "百炼（阿里云 DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "test_model": "qwen-turbo",
    },
]

DEFAULT_PLATFORM = "bailian"

# 兼容旧引用：默认平台（百炼）的 OpenAI 兼容接入地址
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

# 视觉（多模态）模型：处理图片附件的 OCR 与看图。
# 必须是当前平台（百炼 / DashScope 兼容接口）支持的多模态模型。
# 若你的平台网关使用自定义模型 id，请改成对应的多模态模型名。
VISION_MODEL = "qwen-vl-plus"

# 兼容旧引用：默认模型名称
MODEL_NAME = DEFAULT_MODEL

# 回答模式：快速模式直接作答，思考模式开启深度思考并在界面展示推理过程
MODES = [
    {"id": "fast", "name": "快速模式", "description": "直接回答，低延迟", "enable_thinking": False},
    {"id": "thinking", "name": "思考模式", "description": "深度思考后再回答", "enable_thinking": True},
]

# 默认模式
DEFAULT_MODE = "fast"

# 应用名称
APP_NAME = "OpenUnknown"

# LangSmith 追踪（可选）：在 .env 里设置 LANGSMITH_API_KEY 即自动开启。
# LangGraph/LangChain 应用无需额外埋点代码，环境变量生效即可，详见 README。
# 未显式指定项目名时，默认用应用名作为 LangSmith 项目名，便于控制台区分。
if not os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
    os.environ["LANGSMITH_PROJECT"] = APP_NAME

_MODEL_IDS = {m["id"] for m in AVAILABLE_MODELS}
_MODE_IDS = {m["id"] for m in MODES}


def is_valid_model(model_id: str) -> bool:
    """校验模型 id 是否在可选列表内。"""
    return model_id in _MODEL_IDS


def is_valid_mode(mode_id: str) -> bool:
    """校验模式 id 是否在可选列表内。"""
    return mode_id in _MODE_IDS


def mode_enables_thinking(mode_id: str) -> bool:
    """判断指定模式是否需要开启深度思考。"""
    for m in MODES:
        if m["id"] == mode_id:
            return bool(m.get("enable_thinking"))
    return False


def get_platform(platform_id: str) -> dict:
    """按 id 返回平台配置，未知平台抛出 ValueError。"""
    for p in PLATFORMS:
        if p["id"] == platform_id:
            return p
    raise ValueError(f"未知的模型服务平台: {platform_id}")


def is_valid_platform(platform_id: str) -> bool:
    """校验平台 id 是否受支持。"""
    return any(p["id"] == platform_id for p in PLATFORMS)
