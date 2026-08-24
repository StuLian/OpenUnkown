"""会话元数据存储、MCP配置与 sqlite 连接管理。

checkpoint 数据由 SqliteSaver 自行管理(建 checkpoints 等表)，
会话标题/时间等元数据由本模块管理(sessions 表)，
MCP Server 配置由本模块管理(mcp_servers 表)，共用同一个 db 文件。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

# 数据库文件位置: 项目根目录下 data/openunknown.db
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "openunknown.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 元数据操作的互斥锁(sqlite 连接在多线程下需要串行访问)
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    """获取元数据连接(单例)，开启 WAL 模式提升并发读写。"""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_servers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                server_type TEXT NOT NULL,
                command TEXT,
                args TEXT,
                env TEXT,
                url TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        _conn.commit()
    return _conn


def _truncate(text: str, n: int = 24) -> str:
    """把首条消息截断作为会话标题。"""
    text = text.strip().replace("\n", " ")
    return text[:n] + ("..." if len(text) > n else "")


def create_session(session_id: str, title: str) -> None:
    """新建会话元数据(若已存在则忽略)。"""
    now = time.time()
    with _lock:
        get_conn().execute(
            "INSERT OR IGNORE INTO sessions(id, title, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (session_id, _truncate(title), now, now),
        )
        get_conn().commit()


def touch_session(session_id: str, title: str | None = None) -> None:
    """更新会话的更新时间，可选更新标题。"""
    now = time.time()
    with _lock:
        if title:
            get_conn().execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (_truncate(title), now, session_id),
            )
        else:
            get_conn().execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        get_conn().commit()


def list_sessions() -> list[dict]:
    """按最近更新倒序返回会话列表。"""
    with _lock:
        rows = get_conn().execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """删除会话元数据及其全部 checkpoint 数据。"""
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        # AsyncSqliteSaver 建的表(checkpoints / writes)，按 thread_id 清理
        for tbl in ("checkpoints", "writes"):
            conn.execute(f"DELETE FROM {tbl} WHERE thread_id = ?", (session_id,))
        conn.commit()


# ===== MCP Server 配置持久化 =====

def _format_mcp_row(row: sqlite3.Row) -> dict:
    """格式化 MCP 数据库行转为字典对象。"""
    d = dict(row)
    d["args"] = json.loads(d["args"]) if d.get("args") else []
    d["env"] = json.loads(d["env"]) if d.get("env") else {}
    d["enabled"] = bool(d.get("enabled", 1))
    return d


def list_mcp_servers(enabled_only: bool = False) -> list[dict]:
    """获取所有 MCP Server 配置列表。"""
    with _lock:
        query = "SELECT * FROM mcp_servers"
        params: tuple = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at ASC"
        rows = get_conn().execute(query, params).fetchall()
    return [_format_mcp_row(r) for r in rows]


def get_mcp_server(server_id: str) -> dict | None:
    """获取指定 MCP Server 配置。"""
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()
    return _format_mcp_row(row) if row else None


def save_mcp_server(data: dict) -> dict:
    """保存或更新 MCP Server 配置。"""
    server_id = data.get("id") or ("mcp-" + uuid.uuid4().hex[:8])
    name = data.get("name", "").strip() or "未命名服务"
    server_type = data.get("server_type", "stdio").strip().lower()
    command = data.get("command", "").strip() if server_type == "stdio" else None
    args = json.dumps(data.get("args", []) if isinstance(data.get("args"), list) else [])
    env = json.dumps(data.get("env", {}) if isinstance(data.get("env"), dict) else {})
    url = data.get("url", "").strip() if server_type in ("sse", "http") else None
    enabled = 1 if data.get("enabled", True) else 0
    now = time.time()

    with _lock:
        conn = get_conn()
        existing = conn.execute("SELECT id, created_at FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE mcp_servers
                SET name = ?, server_type = ?, command = ?, args = ?, env = ?, url = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, server_type, command, args, env, url, enabled, now, server_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO mcp_servers(id, name, server_type, command, args, env, url, enabled, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (server_id, name, server_type, command, args, env, url, enabled, now, now),
            )
        conn.commit()

    return get_mcp_server(server_id)  # type: ignore


def delete_mcp_server(server_id: str) -> bool:
    """删除指定 MCP Server 配置。"""
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        conn.commit()
    return cur.rowcount > 0


def toggle_mcp_server(server_id: str, enabled: bool) -> dict | None:
    """切换 MCP Server 启用/禁用状态。"""
    now = time.time()
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now, server_id),
        )
        conn.commit()
    return get_mcp_server(server_id)


def import_mcp_servers_from_json(raw_json: dict) -> list[dict]:
    """从标准的 mcpServers JSON 格式批量导入配置 (兼容 Claude Desktop / Cursor 格式)。"""
    servers_dict = raw_json.get("mcpServers") or raw_json
    imported: list[dict] = []

    for name, cfg in servers_dict.items():
        if not isinstance(cfg, dict):
            continue
        server_type = "sse" if "url" in cfg else "stdio"
        item = {
            "name": name,
            "server_type": server_type,
            "command": cfg.get("command"),
            "args": cfg.get("args", []),
            "env": cfg.get("env", {}),
            "url": cfg.get("url"),
            "enabled": True,
        }
        res = save_mcp_server(item)
        imported.append(res)
    return imported
