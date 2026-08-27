"""登录密码的传输加密：RSA-OAEP 加密 + 一次性 nonce 防重放。

前端在提交登录/注册前，先请求 ``GET /api/auth/challenge`` 拿到服务端 RSA 公钥与
一次性 nonce，再用公钥对密码做 RSA-OAEP-SHA256 加密后上传，因此请求体中不再出现
明文密码，密码只在服务端进程内用私钥解出后进入既有的 PBKDF2 校验流程。

私钥仅在服务端存在，首次使用时生成并保存到 ``data/.app_auth_key``（chmod 600），
与既有的 .app_secret / .app_master_key 同级，永远不出服务端进程边界。

安全边界说明：该方案保证「请求体 / 日志 / 抓包中不出现原始密码」，但无法抵御已
完全控制浏览器本地的攻击者（例如能读取 input.value 或注入脚本）——密码在加密前
本就以明文存在于输入框与 JS 内存中。传输层安全仍应依赖 HTTPS（TLS）。
"""
from __future__ import annotations

import base64
import secrets
import threading
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_PRIVATE_KEY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / ".app_auth_key"
)

# nonce 有效期（秒）与内存上限（防恶意刷 challenge 撑爆内存）
_NONCE_TTL_SECONDS = 300
_MAX_NONCES = 10_000

_key_cache: rsa.RSAPrivateKey | None = None
_nonces: dict[str, float] = {}
_lock = threading.Lock()


def _get_private_key() -> rsa.RSAPrivateKey:
    """读取或首次生成 RSA 私钥（2048 位），进程内缓存。"""
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    with _lock:
        if _key_cache is not None:
            return _key_cache
        if _PRIVATE_KEY_PATH.exists():
            _key_cache = serialization.load_pem_private_key(
                _PRIVATE_KEY_PATH.read_bytes(), password=None
            )
        else:
            _key_cache = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            _PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _PRIVATE_KEY_PATH.write_bytes(
                _key_cache.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            try:
                _PRIVATE_KEY_PATH.chmod(0o600)
            except OSError:
                pass
    return _key_cache


def get_public_key_pem() -> str:
    """返回 SPKI 格式的 RSA 公钥 PEM（下发给前端用于加密密码）。"""
    return (
        _get_private_key()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def decrypt_password(ciphertext_b64: str) -> str | None:
    """用私钥对 RSA-OAEP-SHA256 密文解密，失败返回 None。"""
    try:
        ciphertext = base64.b64decode(ciphertext_b64.encode("ascii"))
        plaintext = _get_private_key().decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return plaintext.decode("utf-8")
    except Exception:
        return None


def issue_nonce() -> str:
    """签发一次性 nonce，返回给前端。"""
    nonce = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        if len(_nonces) >= _MAX_NONCES:
            _nonces.clear()  # 简单兜底：超量时清空，防止内存无限增长
        _nonces[nonce] = now
    return nonce


def consume_nonce(nonce: str) -> bool:
    """消费 nonce：一次性且未过期返回 True，否则 False。"""
    with _lock:
        issued = _nonces.pop(nonce, None)
    if issued is None:
        return False
    return (time.time() - issued) <= _NONCE_TTL_SECONDS
