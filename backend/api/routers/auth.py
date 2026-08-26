"""认证接口：注册、登录、当前用户信息与退出登录。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend import store
from backend.api.schemas import LoginRequest, RegisterRequest
from backend.auth import service
from backend.auth.deps import get_current_user_id
from backend.auth.tokens import create_token
from backend.config import DEFAULT_PLATFORM
from backend.security import crypto

router = APIRouter(prefix="/api/auth", tags=["auth"])

_MIN_USERNAME = 3
_MAX_USERNAME = 32
_MIN_PASSWORD = 6


def _validate_credentials(username: str, password: str) -> tuple[str, str]:
    username = (username or "").strip()
    password = password or ""
    if not (_MIN_USERNAME <= len(username) <= _MAX_USERNAME):
        raise HTTPException(
            status_code=400,
            detail=f"用户名长度需在 {_MIN_USERNAME}-{_MAX_USERNAME} 个字符之间",
        )
    if len(password) < _MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"密码至少 {_MIN_PASSWORD} 位")
    return username, password


def _user_view(user: dict) -> dict:
    return {
        "user_id": user["id"],
        "username": user["username"],
        "has_api_key": service.has_api_key(user["id"], DEFAULT_PLATFORM),
    }


@router.post("/register")
def register(req: RegisterRequest) -> dict:
    """注册新用户并直接登录，返回 JWT 与用户信息。"""
    username, password = _validate_credentials(req.username, req.password)
    if store.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    dek_ciphertext = service.generate_dek_ciphertext()
    user = store.create_user(
        username, crypto.hash_password(password), crypto.make_salt(), dek_ciphertext
    )
    return {"token": create_token(user["id"]), "user": _user_view(user)}


@router.post("/login")
def login(req: LoginRequest) -> dict:
    """校验用户名密码，登录成功后返回 JWT 与用户信息。"""
    username = (req.username or "").strip()
    user = store.get_user_by_username(username)
    if not user or not crypto.verify_password(req.password or "", user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": create_token(user["id"]), "user": _user_view(user)}


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回当前登录用户信息。"""
    user = store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return _user_view(user)


@router.post("/logout")
def logout(user_id: str = Depends(get_current_user_id)) -> dict:
    """退出登录。JWT 无状态，服务端无需清理；客户端自行删除令牌即可。"""
    return {"ok": True}
