"""MCP Server 管理相关接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend import store
from backend.agent import mcp
from backend.api.schemas import (
    McpImportRequest,
    McpServerSaveRequest,
    McpToggleRequest,
)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
def get_mcp_servers() -> dict:
    """获取所有 MCP Server 配置。"""
    return {"servers": store.list_mcp_servers()}


@router.post("/servers")
def save_mcp_server(req: McpServerSaveRequest) -> dict:
    """保存或更新单个 MCP Server 配置。"""
    res = store.save_mcp_server(req.model_dump())
    # 连接参数可能已变，让下一轮对话重新拉工具列表
    mcp.invalidate_mcp_cache(res["id"] if res else None)
    return {"server": res}


@router.delete("/servers/{server_id}")
def delete_mcp_server(server_id: str) -> dict:
    """删除指定 MCP Server 配置。"""
    ok = store.delete_mcp_server(server_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    mcp.invalidate_mcp_cache(server_id)
    return {"ok": True}


@router.patch("/servers/{server_id}/toggle")
def toggle_mcp_server(server_id: str, req: McpToggleRequest) -> dict:
    """切换指定 MCP Server 启用状态。"""
    res = store.toggle_mcp_server(server_id, req.enabled)
    if not res:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"server": res}


@router.post("/test")
async def test_mcp_connection(req: McpServerSaveRequest) -> dict:
    """测试连接 MCP Server 并获取它所提供的 Tools 列表。"""
    try:
        tools = await mcp.test_mcp_server(req.model_dump())
        return {"ok": True, "tools": tools}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tools": []}


@router.post("/import")
def import_mcp_json(req: McpImportRequest) -> dict:
    """从标准 JSON 批量导入 MCP Servers。"""
    try:
        imported = store.import_mcp_servers_from_json(req.config)
        mcp.invalidate_mcp_cache()
        return {"ok": True, "imported_count": len(imported), "servers": imported}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}")
