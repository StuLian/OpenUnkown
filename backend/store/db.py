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
                user_id TEXT,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        # 迁移：为旧库 sessions 表补充 user_id 列（存在则忽略）
        try:
            _conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass
        # 迁移：删除历史「无身份」会话及其 checkpoint 数据（含 chat 历史）
        try:
            orphan_ids = [
                r["id"]
                for r in _conn.execute(
                    "SELECT id FROM sessions WHERE user_id IS NULL OR user_id = ''"
                ).fetchall()
            ]
            if orphan_ids:
                _conn.execute(
                    "DELETE FROM sessions WHERE user_id IS NULL OR user_id = ''"
                )
                for tid in orphan_ids:
                    for tbl in ("checkpoints", "writes"):
                        try:
                            _conn.execute(
                                f"DELETE FROM {tbl} WHERE thread_id = ?", (tid,)
                            )
                        except sqlite3.OperationalError:
                            pass  # 表尚不存在（全新库）
        except Exception:
            pass
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_servers (
                id TEXT PRIMARY KEY,
                user_id TEXT,
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
        # 迁移：为旧库 mcp_servers 表补充 user_id 列（存在则忽略），
        # 并删除历史「无身份」的 MCP 配置。
        try:
            _conn.execute("ALTER TABLE mcp_servers ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass
        _conn.execute(
            "DELETE FROM mcp_servers WHERE user_id IS NULL OR user_id = ''"
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                kdf_salt TEXT NOT NULL,
                dek_ciphertext TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        # 迁移：为旧库 users 表补充 dek_ciphertext 列（存在则忽略）
        try:
            _conn.execute("ALTER TABLE users ADD COLUMN dek_ciphertext TEXT")
        except sqlite3.OperationalError:
            pass
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_api_keys (
                user_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                ciphertext TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, platform)
            )
            """
        )
        # 迁移：把历史明文 env 加密为密文（幂等：仅处理以 '{' 开头的明文 JSON）。
        # 失败不影响启动，读取侧已对明文 JSON 做兼容回退。
        try:
            from backend.security.master_key import encrypt_secret

            rows = _conn.execute(
                "SELECT id, env FROM mcp_servers WHERE env IS NOT NULL AND env != ''"
            ).fetchall()
            for r in rows:
                env = r["env"]
                if env.startswith("{"):
                    _conn.execute(
                        "UPDATE mcp_servers SET env = ? WHERE id = ?",
                        (encrypt_secret(env), r["id"]),
                    )
        except Exception:
            pass
        _conn.commit()
    return _conn
