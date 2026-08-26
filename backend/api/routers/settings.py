"""应用设置接口：模型服务 ApiKey 的查询、保存、清除与连通性测试。

所有接口均要求登录；ApiKey 以密文存储（见 backend.auth.service），
接口不回传明文。
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend import store
from backend.agent.llm import invalidate_llm_cache
from backend.api.schemas import ApiKeyTestRequest, ApiKeyUpdateRequest
from backend.auth import service
from backend.auth.deps import get_current_user_id
from backend.config import DEFAULT_PLATFORM, PLATFORMS, get_platform, is_valid_platform

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _mask_key(key: str) -> str:
    """把 Key 打成 sk-****abcd 形式，避免完整回显。"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:4] + "****" + key[-4:]


@router.get("")
def get_settings(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回当前用户的 ApiKey 配置状态（不回传明文）。"""
    platform = DEFAULT_PLATFORM
    masked = ""
    has_key = service.has_api_key(user_id, platform)
    if has_key:
        masked = _mask_key(service.resolve_api_key(user_id, platform) or "")
    return {
        "platforms": PLATFORMS,
        "default_platform": DEFAULT_PLATFORM,
        "current": {"platform": platform, "has_key": has_key, "key_masked": masked},
    }


@router.put("/api-key")
def update_api_key(
    req: ApiKeyUpdateRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """加密保存当前用户的 ApiKey（默认百炼平台）。"""
    platform = req.platform or DEFAULT_PLATFORM
    if not is_valid_platform(platform):
        raise HTTPException(status_code=400, detail="不支持的平台")
    key = (req.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="ApiKey 不能为空")
    service.save_api_key(user_id, platform, key)
    invalidate_llm_cache()
    return {"ok": True, "platform": platform, "key_masked": _mask_key(key)}


@router.delete("/api-key")
def clear_api_key(
    user_id: str = Depends(get_current_user_id), platform: str = DEFAULT_PLATFORM
) -> dict:
    """删除当前用户的 ApiKey，删除后该用户无法再调用模型服务。"""
    if not is_valid_platform(platform):
        raise HTTPException(status_code=400, detail="不支持的平台")
    store.delete_user_api_key(user_id, platform)
    invalidate_llm_cache()
    return {"ok": True, "platform": platform, "has_key": False}


@router.post("/test")
async def test_api_key(
    req: ApiKeyTestRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """用给定 Key 发起一次最小化调用，验证其是否可用。"""
    platform = req.platform or DEFAULT_PLATFORM
    if not is_valid_platform(platform):
        return {"ok": False, "error": "不支持的平台"}
    key = (req.api_key or "").strip()
    if not key:
        return {"ok": False, "error": "请输入 ApiKey"}
    plat = get_platform(platform)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{plat['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": plat["test_model"],
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "stream": False,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"请求失败: {exc}"}

    if resp.status_code == 200:
        return {"ok": True}

    detail = ""
    try:
        data = resp.json()
        detail = (
            data.get("error", {}).get("message")
            or data.get("message")
            or data.get("error")
            or ""
        )
    except Exception:  # noqa: BLE001
        detail = resp.text[:200]
    return {"ok": False, "error": f"HTTP {resp.status_code}: {detail}"}
