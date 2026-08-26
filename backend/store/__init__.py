"""持久化层：会话元数据、MCP 配置、用户与 ApiKey 密文、sqlite 连接管理。

对外统一通过 ``from backend import store`` 使用，这里重新导出各子模块的公共函数。
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
    get_session,
    list_sessions,
    thread_id_for,
    touch_session,
)
from backend.store.users import (
    create_user,
    delete_user_api_key,
    get_user_api_key_cipher,
    get_user_by_id,
    get_user_by_username,
    list_user_platforms,
    set_user_api_key,
)

__all__ = [
    "get_conn",
    "create_session",
    "touch_session",
    "get_session",
    "list_sessions",
    "delete_session",
    "thread_id_for",
    "list_mcp_servers",
    "get_mcp_server",
    "save_mcp_server",
    "delete_mcp_server",
    "toggle_mcp_server",
    "import_mcp_servers_from_json",
    "create_user",
    "get_user_by_username",
    "get_user_by_id",
    "set_user_api_key",
    "get_user_api_key_cipher",
    "delete_user_api_key",
    "list_user_platforms",
]
