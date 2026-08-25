"""聊天问答与模型/模式元信息相关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.config import (
    AVAILABLE_MODELS,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    MODES,
    is_valid_mode,
    is_valid_model,
)
from backend.api.schemas import ChatRequest
from backend.api.streaming import stream_answer

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """流式问答接口。"""
    # 校验模型，非法或缺省时用默认模型（前端选择器只提供合法值，此处兜住异常入参）
    model = req.model if req.model and is_valid_model(req.model) else DEFAULT_MODEL
    # 校验模式，非法或缺省时用默认模式
    mode = req.mode if req.mode and is_valid_mode(req.mode) else DEFAULT_MODE
    return StreamingResponse(
        stream_answer(req.message, req.session_id, model, mode, request),
        media_type="text/event-stream",
    )


@router.get("/models")
def list_models() -> dict:
    """返回可选模型列表与默认模型。"""
    return {"models": AVAILABLE_MODELS, "default": DEFAULT_MODEL}


@router.get("/modes")
def list_modes() -> dict:
    """返回可选回答模式列表与默认模式。"""
    return {"modes": MODES, "default": DEFAULT_MODE}
