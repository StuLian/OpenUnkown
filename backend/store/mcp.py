"""MCP Server 配置持久化(mcp_servers 表)，按用户隔离。

env 字段可能包含访问令牌等敏感信息，落库前用服务端主密钥加密，
读取时解密返回（对旧版明文 JSON 做向后兼容）。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from backend.security.master_key import decrypt_secret, encrypt_secret
from backend.store.db import _lock, get_conn


def _encrypt_env(env: dict) -> str:
    """把 env 字典序列化并加密为 Fernet token。"""
    return encrypt_secret(json.dumps(env))


def _decrypt_env(raw: str | None) -> dict:
    """解密 env 字段为字典；旧版明文 JSON 数据自动兼容。"""
    if not raw:
        return {}
    plaintext = decrypt_secret(raw)
    if plaintext is None:
        plaintext = raw  # 旧数据为明文 JSON
    try:
        return json.loads(plaintext)
    except (ValueError, TypeError):
        return {}


def _format_mcp_row(row: sqlite3.Row) -> dict:
    """格式化 MCP 数据库行转为字典对象。"""
    d = dict(row)
    d["args"] = json.loads(d["args"]) if d.get("args") else []
    d["env"] = _decrypt_env(d.get("env"))
    d["enabled"] = bool(d.get("enabled", 1))
    return d


def list_mcp_servers(user_id: str, enabled_only: bool = False) -> list[dict]:
    """获取指定用户的 MCP Server 配置列表。"""
    with _lock:
        query = "SELECT * FROM mcp_servers WHERE user_id = ?"
        params: list = [user_id]
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY created_at ASC"
        rows = get_conn().execute(query, params).fetchall()
    return [_format_mcp_row(r) for r in rows]


def get_mcp_server(user_id: str, server_id: str) -> dict | None:
    """获取指定用户名下的 MCP Server 配置。"""
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM mcp_servers WHERE id = ? AND user_id = ?",
            (server_id, user_id),
        ).fetchone()
    return _format_mcp_row(row) if row else None


def save_mcp_server(user_id: str, data: dict) -> dict:
    """保存或更新指定用户的 MCP Server 配置。

    编辑他人名下的 server 会抛出 PermissionError。
    """
    server_id = data.get("id") or ("mcp-" + uuid.uuid4().hex[:8])
    name = data.get("name", "").strip() or "未命名服务"
    server_type = data.get("server_type", "stdio").strip().lower()
    command = data.get("command", "").strip() if server_type == "stdio" else None
    args = json.dumps(data.get("args", []) if isinstance(data.get("args"), list) else [])
    env = _encrypt_env(data.get("env", {}) if isinstance(data.get("env"), dict) else {})
    url = data.get("url", "").strip() if server_type in ("sse", "http") else None
    enabled = 1 if data.get("enabled", True) else 0
    now = time.time()

    with _lock:
        conn = get_conn()
        existing = conn.execute(
            "SELECT id, user_id, created_at FROM mcp_servers WHERE id = ?", (server_id,)
        ).fetchone()
        if existing and existing["user_id"] != user_id:
            raise PermissionError("无权修改该 MCP Server")
        if existing:
            conn.execute(
                """
                UPDATE mcp_servers
                SET name = ?, server_type = ?, command = ?, args = ?, env = ?, url = ?, enabled = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (name, server_type, command, args, env, url, enabled, now, server_id, user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO mcp_servers(id, user_id, name, server_type, command, args, env, url, enabled, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (server_id, user_id, name, server_type, command, args, env, url, enabled, now, now),
            )
        conn.commit()

    return get_mcp_server(user_id, server_id)  # type: ignore


def delete_mcp_server(user_id: str, server_id: str) -> bool:
    """删除指定用户名下的 MCP Server 配置。"""
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM mcp_servers WHERE id = ? AND user_id = ?",
            (server_id, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def toggle_mcp_server(user_id: str, server_id: str, enabled: bool) -> dict | None:
    """切换指定用户名下的 MCP Server 启用/禁用状态。"""
    now = time.time()
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (1 if enabled else 0, now, server_id, user_id),
        )
        conn.commit()
    return get_mcp_server(user_id, server_id)


def import_mcp_servers_from_json(user_id: str, raw_json: dict) -> list[dict]:
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
        res = save_mcp_server(user_id, item)
        imported.append(res)
    return imported
