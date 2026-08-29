"""文件上传与解析接口。

上传文件后立即解析为纯文本并返回，前端拿到解析结果后作为对话附件发送；
解析本身不调用模型服务，因此不依赖 ApiKey。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.auth.deps import get_current_user_id
from backend.files import parser

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/limits")
def limits(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回上传限制，供前端做上传前的本地校验。"""
    return {
        "extensions": list(parser.ALLOWED_EXTENSIONS),
        "max_file_size": parser.MAX_FILE_SIZE,
        "max_content_chars": parser.MAX_CONTENT_CHARS,
    }


@router.post("")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """接收单个文件并解析为纯文本。"""
    data = await file.read()
    try:
        parsed = parser.parse_bytes(file.filename or "", data)
    except parser.ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败: {exc}") from exc

    return {
        "ok": True,
        "filename": parsed.filename,
        "file_type": parsed.file_type,
        "size": parsed.size,
        "char_count": parsed.char_count,
        "content": parsed.content,
        "truncated": parsed.truncated,
    }
