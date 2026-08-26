"""服务端主密钥：加密全局共享配置中的敏感字段（如 MCP 的 env）。

与「用户密码派生的 ApiKey 密钥」相互独立：MCP 配置全局共享，任意登录用户
触发的工具调用都发生在服务端，因此用服务端主密钥加密。
密钥在首次使用时自动生成并保存到 ``data/.app_master_key``（chmod 600）。
"""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MASTER_KEY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".app_master_key"


def _load_or_create_key() -> bytes:
    """读取或首次生成主密钥。"""
    if MASTER_KEY_PATH.exists():
        return MASTER_KEY_PATH.read_text(encoding="utf-8").strip().encode("ascii")
    key = Fernet.generate_key()
    MASTER_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_KEY_PATH.write_text(key.decode("ascii"), encoding="utf-8")
    try:
        MASTER_KEY_PATH.chmod(0o600)
    except OSError:
        pass
    return key


def encrypt_secret(plaintext: str) -> str:
    """用主密钥加密一段文本，返回 Fernet token 字符串。"""
    return Fernet(_load_or_create_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str | None:
    """用主密钥解密；密钥不匹配或数据损坏时返回 None。"""
    try:
        return Fernet(_load_or_create_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
