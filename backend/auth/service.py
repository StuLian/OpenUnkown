"""用户 ApiKey 的加密存取与解析（业务层，信封加密）。

每个用户持有一个随机生成的 DEK（Fernet 密钥），ApiKey 用 DEK 加密后落库；
DEK 本身用服务端主密钥包裹（加密）后存到 users.dek_ciphertext。

这样：
- ApiKey 明文不落库；
- 解密所需的 DEK 可从磁盘恢复，服务重启后**无需重新登录**。
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from backend.security import crypto
from backend.security.master_key import decrypt_secret, encrypt_secret
from backend.store import users as user_store


def _generate_dek() -> bytes:
    """生成随机 DEK（Fernet 密钥）。"""
    return Fernet.generate_key()


def generate_dek_ciphertext() -> str:
    """生成随机 DEK 并用主密钥包裹，返回密文（用于新建用户）。"""
    return encrypt_secret(_generate_dek().decode("ascii"))


def _ensure_user_dek(user_id: str) -> bytes:
    """获取用户的 DEK；首次使用时生成并落库。"""
    user = user_store.get_user_by_id(user_id)
    if not user:
        raise ValueError("用户不存在")

    dek_ciphertext = user.get("dek_ciphertext")
    if dek_ciphertext:
        dek = decrypt_secret(dek_ciphertext)
        if dek:
            return dek.encode("ascii")

    # 旧用户或缺失 DEK：生成一个随机 DEK 并用主密钥包裹后落库
    dek = _generate_dek()
    user_store.set_user_dek(user_id, encrypt_secret(dek.decode("ascii")))
    return dek


def save_api_key(user_id: str, platform: str, api_key: str) -> None:
    """加密并保存指定用户的 ApiKey。"""
    dek = _ensure_user_dek(user_id)
    ciphertext = crypto.encrypt_apikey(api_key.strip(), dek)
    user_store.set_user_api_key(user_id, platform, ciphertext)


def resolve_api_key(user_id: str, platform: str) -> str | None:
    """解密并返回指定用户的 ApiKey；未配置或无法解密返回 None。"""
    ciphertext = user_store.get_user_api_key_cipher(user_id, platform)
    if not ciphertext:
        return None
    dek = _ensure_user_dek(user_id)
    return crypto.decrypt_apikey(ciphertext, dek)


def has_api_key(user_id: str, platform: str) -> bool:
    """判断指定用户是否已配置指定平台的 ApiKey（不要求可解密）。"""
    return user_store.get_user_api_key_cipher(user_id, platform) is not None
