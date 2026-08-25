"""API 请求体的 Pydantic 模型定义。"""
from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """聊天请求体。"""

    message: str
    session_id: str
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
