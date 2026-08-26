"""MCP Server 管理相关接口（按用户隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend import store
from backend.agent import mcp
from backend.api.schemas import (
    McpImportRequest,
    McpServerSaveRequest,
    McpToggleRequest,
)
from backend.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
def get_mcp_servers(user_id: str = Depends(get_current_user_id)) -> dict:
    """获取当前用户的所有 MCP Server 配置。"""
    return {"servers": store.list_mcp_servers(user_id)}


@router.post("/servers")
def save_mcp_server(
    req: McpServerSaveRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """保存或更新当前用户的单个 MCP Server 配置。"""
    try:
        res = store.save_mcp_server(user_id, req.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    # 连接参数可能已变，让下一轮对话重新拉工具列表
    mcp.invalidate_mcp_cache(res["id"] if res else None)
    return {"server": res}


@router.delete("/servers/{server_id}")
def delete_mcp_server(
    server_id: str, user_id: str = Depends(get_current_user_id)
) -> dict:
    """删除当前用户的指定 MCP Server 配置。"""
    ok = store.delete_mcp_server(user_id, server_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    mcp.invalidate_mcp_cache(server_id)
    return {"ok": True}


@router.patch("/servers/{server_id}/toggle")
def toggle_mcp_server(
    server_id: str, req: McpToggleRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """切换当前用户的指定 MCP Server 启用状态。"""
    res = store.toggle_mcp_server(user_id, server_id, req.enabled)
    if not res:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"server": res}


@router.post("/test")
async def test_mcp_connection(
    req: McpServerSaveRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """测试连接 MCP Server 并获取它所提供的 Tools 列表。"""
    try:
        tools = await mcp.test_mcp_server(req.model_dump())
        return {"ok": True, "tools": tools}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tools": []}


@router.post("/import")
def import_mcp_json(
    req: McpImportRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """从标准 JSON 批量导入 MCP Servers 到当前用户名下。"""
    try:
        imported = store.import_mcp_servers_from_json(user_id, req.config)
        mcp.invalidate_mcp_cache()
        return {"ok": True, "imported_count": len(imported), "servers": imported}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败: {exc}")
