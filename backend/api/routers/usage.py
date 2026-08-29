"""token 用量统计接口（只读）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend import store
from backend.auth.deps import get_current_user_id

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("")
def get_usage(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回当前用户的 token 用量汇总（总计 / 按模型 / 按日期）。"""
    return store.usage_stats(user_id)
