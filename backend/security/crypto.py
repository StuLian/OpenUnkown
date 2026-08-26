"""密码散列与 ApiKey 加密/解密。

安全约定：
- 用户密码只保存 PBKDF2-SHA256 散列，用于登录校验，明文不落库；
- ApiKey 用 Fernet 对称加密，明文永不落库。加密所用的 DEK 由服务端主密钥包裹后
  落库（见 backend.auth.service），服务重启后可恢复。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

# 登录密码散列迭代次数
_PBKDF2_ITERATIONS = 200_000


def make_salt(nbytes: int = 16) -> str:
    """生成随机盐（URL-safe base64 字符串）。"""
    return base64.urlsafe_b64encode(os.urandom(nbytes)).decode("ascii")


def hash_password(password: str) -> str:
    """对密码做 PBKDF2 散列，返回自描述字符串 `pbkdf2_sha256$iters$salt$hash`。"""
    salt = make_salt()
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}"
        f"${base64.urlsafe_b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否匹配已保存的散列，恒定时间比较。"""
    try:
        _algo, iters, salt, hash_b64 = stored.split("$")
        iters = int(iters)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iters
    )
    expected = base64.urlsafe_b64encode(dk).decode("ascii")
    return hmac.compare_digest(expected, hash_b64)


def encrypt_apikey(plaintext: str, fernet_key: bytes) -> str:
    """用 Fernet 加密 ApiKey，返回 URL-safe token 字符串。"""
    return Fernet(fernet_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_apikey(ciphertext: str, fernet_key: bytes) -> str | None:
    """用 Fernet 解密 ApiKey；密钥不匹配或数据损坏时返回 None。"""
    try:
        return Fernet(fernet_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
