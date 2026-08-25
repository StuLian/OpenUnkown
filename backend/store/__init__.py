"""持久化层：会话元数据、MCP 配置与 sqlite 连接管理。

对外统一通过 ``from backend import store`` 使用，这里重新导出各子模块的公共函数，
保持与拆分前完全一致的调用方式(store.list_sessions() 等)。
"""
from backend.store.db import get_conn
from backend.store.mcp import (
    delete_mcp_server,
    get_mcp_server,
    import_mcp_servers_from_json,
    list_mcp_servers,
    save_mcp_server,
    toggle_mcp_server,
)
from backend.store.sessions import (
    create_session,
    delete_session,
    list_sessions,
    touch_session,
)

__all__ = [
    "get_conn",
    "create_session",
    "touch_session",
    "list_sessions",
    "delete_session",
    "list_mcp_servers",
    "get_mcp_server",
    "save_mcp_server",
    "delete_mcp_server",
    "toggle_mcp_server",
    "import_mcp_servers_from_json",
]
