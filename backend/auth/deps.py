"""FastAPI 依赖：从 Authorization 头解析当前登录用户。"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.tokens import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """返回当前登录用户的 user_id；未登录或令牌失效时抛 401。"""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = decode_token(creds.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id
