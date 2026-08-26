"""用户与用户 ApiKey（密文）持久化。"""
from __future__ import annotations

import time
import uuid

from backend.store.db import _lock, get_conn


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def create_user(
    username: str, password_hash: str, kdf_salt: str, dek_ciphertext: str
) -> dict:
    """创建用户，返回完整用户记录。"""
    user_id = _new_id("usr")
    now = time.time()
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO users(id, username, password_hash, kdf_salt, dek_ciphertext, created_at)"
            " VALUES(?, ?, ?, ?, ?, ?)",
            (user_id, username, password_hash, kdf_salt, dek_ciphertext, now),
        )
        conn.commit()
    return get_user_by_id(user_id)  # type: ignore


def set_user_dek(user_id: str, dek_ciphertext: str) -> None:
    """写入（或覆盖）用户的 DEK 密文。"""
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE users SET dek_ciphertext = ? WHERE id = ?",
            (dek_ciphertext, user_id),
        )
        conn.commit()


def get_user_by_username(username: str) -> dict | None:
    """按用户名查询用户。"""
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    """按 id 查询用户。"""
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def set_user_api_key(user_id: str, platform: str, ciphertext: str) -> None:
    """保存（或覆盖）指定用户在指定平台的 ApiKey 密文。"""
    now = time.time()
    with _lock:
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO user_api_keys(user_id, platform, ciphertext, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id, platform)
            DO UPDATE SET ciphertext = excluded.ciphertext, updated_at = excluded.updated_at
            """,
            (user_id, platform, ciphertext, now),
        )
        conn.commit()


def get_user_api_key_cipher(user_id: str, platform: str) -> str | None:
    """读取指定用户在指定平台的 ApiKey 密文。"""
    with _lock:
        row = get_conn().execute(
            "SELECT ciphertext FROM user_api_keys WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        ).fetchone()
    return row["ciphertext"] if row else None


def delete_user_api_key(user_id: str, platform: str) -> bool:
    """删除指定用户在指定平台的 ApiKey，返回是否真的删除过。"""
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM user_api_keys WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        )
        conn.commit()
    return cur.rowcount > 0


def list_user_platforms(user_id: str) -> list[str]:
    """列出用户已配置 ApiKey 的平台 id。"""
    with _lock:
        rows = get_conn().execute(
            "SELECT platform FROM user_api_keys WHERE user_id = ?", (user_id,)
        ).fetchall()
    return [r["platform"] for r in rows]
