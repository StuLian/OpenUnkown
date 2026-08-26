"""JWT 会话令牌签发与校验。

签名密钥在首次启动时自动生成并保存到 ``data/.app_secret``（chmod 600），
属于服务端运维密钥，与用户 ApiKey 的加密密钥（由用户密码派生）无关。
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import jwt

# 签名密钥持久化位置
SECRET_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".app_secret"

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 天


def _load_or_create_secret() -> str:
    """读取或首次生成 JWT 签名密钥。"""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRET_PATH.write_text(secret, encoding="utf-8")
    try:
        SECRET_PATH.chmod(0o600)
    except OSError:
        pass
    return secret


def create_token(user_id: str) -> str:
    """为指定用户签发 JWT。"""
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + _TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _load_or_create_secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> str | None:
    """校验并解析 JWT，返回 user_id；无效或过期返回 None。"""
    try:
        payload = jwt.decode(token, _load_or_create_secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")
