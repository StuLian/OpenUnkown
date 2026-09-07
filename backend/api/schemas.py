"""API 请求体的 Pydantic 模型定义。"""
from __future__ import annotations

from pydantic import BaseModel


class AttachmentRef(BaseModel):
    """聊天请求中的附件引用。

    文本附件：file_type 为文档类型（txt/markdown/csv/pdf/docx/xlsx），content 为解析文本；
    图片附件：file_type 为 "image"，image 为 data URL，content 为 OCR 提取文字（可为空）。
    """

    filename: str
    file_type: str = "text"
    content: str = ""
    image: str | None = None


class FileUrlRequest(BaseModel):
    """粘贴链接下载请求体。"""

    url: str


class ChatRequest(BaseModel):
    """聊天请求体。"""

    message: str
    session_id: str
    model: str | None = None
    mode: str | None = None
    attachments: list[AttachmentRef] = []


class ChatConfirmRequest(BaseModel):
    """飞书写操作人工确认的恢复请求体（/api/chat/confirm）。"""

    session_id: str
    approved: bool
    model: str | None = None
    mode: str | None = None


class McpServerSaveRequest(BaseModel):
    """MCP Server 保存请求体。"""

    id: str | None = None
    name: str
    server_type: str = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    enabled: bool = True


class McpToggleRequest(BaseModel):
    """MCP Server 启停请求体。"""

    enabled: bool


class McpImportRequest(BaseModel):
    """MCP JSON 批量导入请求体。"""

    config: dict


class ApiKeyUpdateRequest(BaseModel):
    """模型服务 ApiKey 保存请求体。"""

    api_key: str
    platform: str = "bailian"


class ApiKeyTestRequest(BaseModel):
    """模型服务 ApiKey 连通性测试请求体。"""

    api_key: str
    platform: str = "bailian"


class RegisterRequest(BaseModel):
    """注册请求体。密码经 RSA-OAEP 加密，请求体中不含明文。"""

    username: str
    password_ciphertext: str
    nonce: str


class LoginRequest(BaseModel):
    """登录请求体。密码经 RSA-OAEP 加密，请求体中不含明文。"""

    username: str
    password_ciphertext: str
    nonce: str
