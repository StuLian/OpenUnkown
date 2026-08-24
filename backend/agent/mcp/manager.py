"""MCP 管理器：拉取工具列表、执行工具调用、组装 LangChain BaseTool。"""
from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import BaseTool, StructuredTool

from backend import store
from backend.agent.mcp.client import connect_server
from backend.agent.mcp.converter import create_args_schema

logger = logging.getLogger(__name__)

# 按 server_id 缓存工具元数据，避免每次对话都冷启动 MCP 子进程拉列表。
# 值为 (连接配置指纹, 工具元数据列表)。
_meta_cache: dict[str, tuple[str, list[dict]]] = {}
_cache_lock = asyncio.Lock()


def _server_fingerprint(cfg: dict) -> str:
    """生成影响 MCP 连接的配置指纹，配置变了才重新拉工具列表。"""
    payload = {
        "server_type": cfg.get("server_type"),
        "command": cfg.get("command"),
        "args": cfg.get("args") or [],
        "env": cfg.get("env") or {},
        "url": cfg.get("url"),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def invalidate_mcp_cache(server_id: str | None = None) -> None:
    """使 MCP 工具列表缓存失效。server_id 为空时清空全部。"""
    if server_id is None:
        _meta_cache.clear()
        logger.info("[MCP] 已清空全部工具列表缓存")
        return
    if _meta_cache.pop(server_id, None) is not None:
        logger.info("[MCP] 已失效工具列表缓存: %s", server_id)


def _prune_stale_cache(alive_ids: set[str]) -> None:
    """清掉已删除 Server 的缓存条目。"""
    for sid in list(_meta_cache):
        if sid not in alive_ids:
            _meta_cache.pop(sid, None)


async def test_mcp_server(cfg: dict) -> list[dict]:
    """测试 MCP Server 连接并返回其提供的工具列表。"""
    async with connect_server(cfg) as session:
        result = await session.list_tools()
        tools_list = []
        for t in result.tools:
            tools_list.append({
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            })
        return tools_list


async def execute_mcp_tool(cfg: dict, tool_name: str, kwargs: dict) -> str:
    """调用具体的 MCP 工具并返回格式化文本。"""
    server_name = cfg.get("name", "unknown")
    logger.info("[MCP] 调用工具 %s::%s, 参数: %s", server_name, tool_name, kwargs)

    async with connect_server(cfg) as session:
        res = await session.call_tool(tool_name, arguments=kwargs)

        # 打印原始返回以便排查准确性问题
        logger.info("[MCP] 工具 %s::%s 原始返回 isError=%s content=%s",
                    server_name, tool_name, res.isError, res.content)

        texts = []
        if res.content:
            for item in res.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
                elif hasattr(item, "data"):
                    texts.append(f"[Binary Data {getattr(item, 'mimeType', '')}]")
                else:
                    texts.append(str(item))
        output = "\n".join(texts)

        logger.info("[MCP] 工具 %s::%s 最终文本输出(前500字): %s",
                    server_name, tool_name, output[:500])

        if res.isError:
            return f"Error executing tool {tool_name}: {output}"
        return output if output else "Tool execution succeeded (empty output)."


def _build_tools_from_meta(server: dict, metas: list[dict]) -> list[BaseTool]:
    """用缓存的工具元数据组装 LangChain StructuredTool，闭包捕获当前配置。"""
    tools: list[BaseTool] = []
    for meta in metas:
        t_name = meta["name"]
        raw_desc = meta.get("description", "") or ""
        t_desc = (
            f"[MCP: {server.get('name', '')}] {raw_desc}"
            if raw_desc
            else f"MCP tool from {server.get('name')}"
        )
        schema = meta.get("inputSchema", {})
        model_name = f"Args_{server['id'].replace('-', '_')}_{t_name}"
        args_schema = create_args_schema(model_name, schema)

        def _make_caller(server_cfg: dict, name: str):
            async def _coroutine(**kwargs) -> str:
                return await execute_mcp_tool(server_cfg, name, kwargs)
            return _coroutine

        tools.append(StructuredTool(
            name=t_name,
            description=t_desc,
            args_schema=args_schema,
            coroutine=_make_caller(server, t_name),
        ))
    return tools


async def _load_server_meta(server: dict) -> list[dict]:
    """读取单个 Server 的工具元数据：指纹命中走缓存，未命中才连 MCP。"""
    server_id = server["id"]
    fingerprint = _server_fingerprint(server)
    cached = _meta_cache.get(server_id)
    if cached and cached[0] == fingerprint:
        logger.info("[MCP] 工具列表缓存命中: %s (%d 个工具)", server.get("name"), len(cached[1]))
        return cached[1]

    logger.info("[MCP] 工具列表缓存未命中，正在连接: %s", server.get("name"))
    metas = await test_mcp_server(server)
    _meta_cache[server_id] = (fingerprint, metas)
    logger.info("[MCP] 已缓存工具列表: %s (%d 个工具)", server.get("name"), len(metas))
    return metas


async def get_enabled_mcp_tools() -> list[BaseTool]:
    """获取当前所有启用的 MCP Server 提供的工具，并封装为 LangChain BaseTool。

    工具列表按 Server 连接配置缓存；真正执行工具时才会再连一次 MCP。
    """
    servers = store.list_mcp_servers(enabled_only=True)
    all_ids = {s["id"] for s in store.list_mcp_servers(enabled_only=False)}
    if not servers:
        _prune_stale_cache(all_ids)
        return []

    tools: list[BaseTool] = []
    async with _cache_lock:
        _prune_stale_cache(all_ids)
        for s in servers:
            try:
                metas = await _load_server_meta(s)
                tools.extend(_build_tools_from_meta(s, metas))
            except Exception as e:
                logger.warning("加载 MCP Server [%s] 失败: %s", s.get("name"), e)

    return tools
