"""sqlite 连接管理：单例连接、互斥锁与表结构初始化。

checkpoint 数据由 SqliteSaver 自行管理(建 checkpoints 等表)，
会话元数据(sessions 表)与 MCP Server 配置(mcp_servers 表)共用同一个 db 文件，
连接与建表统一由本模块负责。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# 数据库文件位置: 项目根目录下 data/openunknown.db
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "openunknown.db"
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
