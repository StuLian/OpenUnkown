"""MCP Server 连接上下文管理：支持 stdio 和 sse 两种连接方式。"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client


@asynccontextmanager
async def connect_server(cfg: dict) -> AsyncGenerator[ClientSession, None]:
    """建立与单个 MCP Server 的连接上下文。"""
    server_type = cfg.get("server_type", "stdio")

    if server_type == "stdio":
        command = cfg.get("command")
        if not command:
            raise ValueError(f"MCP Server [{cfg.get('name')}] 未指定 command")
        args = cfg.get("args") or []
        env_dict = {**os.environ, **(cfg.get("env") or {})}

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env_dict,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    elif server_type in ("sse", "http"):
        url = cfg.get("url")
        if not url:
            raise ValueError(f"MCP Server [{cfg.get('name')}] 未指定 url")
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        raise ValueError(f"不支持的 MCP server_type: {server_type}")
