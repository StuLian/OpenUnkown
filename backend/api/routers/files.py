"""文件上传与解析接口。

文档/表格上传后解析为纯文本；图片上传后仅编码为 data URL（校验 + 缩放），
OCR 延迟到用户真正发送消息时（见 streaming）再执行，避免上传即调用模型造成浪费。
另支持粘贴链接：下载链接内容后走与上传相同的解析流程。
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.api.schemas import FileUrlRequest
from backend.auth.deps import get_current_user_id
from backend.files import image, parser

router = APIRouter(prefix="/api/files", tags=["files"])

# 链接下载时按 Content-Type 推断扩展名（URL 无扩展名时使用）
_CONTENT_TYPE_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

_URL_TIMEOUT = 20.0
_URL_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _process(filename: str, data: bytes) -> dict:
    """按扩展名分发：图片编码，文档/表格解析为纯文本。"""
    ext = (filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext in image.IMAGE_EXTENSIONS:
        try:
            img = image.process_image(filename, data)
        except image.ImageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "file_type": "image",
            "filename": img.filename,
            "size": img.size,
            "mime": img.mime,
            "width": img.width,
            "height": img.height,
            "image": img.data_url,
        }

    if ext not in parser.ALLOWED_EXTENSIONS:
        supported = (
            "文档/表格：" + ", ".join(parser.ALLOWED_EXTENSIONS)
            + "；图片：" + ", ".join(image.IMAGE_EXTENSIONS)
        )
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型「.{ext or '?'}」，仅支持：{supported}",
        )

    try:
        parsed = parser.parse_bytes(filename, data)
    except parser.ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败: {exc}") from exc

    return {
        "ok": True,
        "file_type": parsed.file_type,
        "filename": parsed.filename,
        "size": parsed.size,
        "char_count": parsed.char_count,
        "content": parsed.content,
        "truncated": parsed.truncated,
    }


def _filename_from_url(url: str, content_type: str) -> str:
    """从 URL 路径与 Content-Type 推断文件名，供类型分发使用。"""
    path = urlparse(url).path
    base = unquote(path.rsplit("/", 1)[-1]).strip() if path else ""
    if base:
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if ext in image.IMAGE_EXTENSIONS or ext in parser.ALLOWED_EXTENSIONS:
            return base
    # 无扩展名 / 未知扩展名：按 Content-Type 推断
    inferred = _CONTENT_TYPE_EXT.get(content_type)
    stem = base.rsplit(".", 1)[0] if "." in base else base
    if inferred:
        return (stem or "下载文件") + "." + inferred
    return base or "下载文件"


@router.get("/limits")
def limits(user_id: str = Depends(get_current_user_id)) -> dict:
    """返回上传限制，供前端做上传前的本地校验。"""
    return {
        "extensions": list(parser.ALLOWED_EXTENSIONS),
        "image_extensions": list(image.IMAGE_EXTENSIONS),
        "max_file_size": parser.MAX_FILE_SIZE,
        "max_image_size": image.MAX_IMAGE_SIZE,
        "max_content_chars": parser.MAX_CONTENT_CHARS,
    }


@router.post("")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """接收单个文件并解析：文档/表格转文本，图片编码为 data URL。"""
    data = await file.read()
    return _process(file.filename or "", data)


@router.post("/url")
async def upload_from_url(
    req: FileUrlRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """下载链接内容并走与上传相同的解析流程（图片仅编码，OCR 延迟到发送时）。"""
    url = (req.url or "").strip()
    if not re.match(r"^https?://\S+$", url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="仅支持 http/https 链接")

    try:
        async with httpx.AsyncClient(
            timeout=_URL_TIMEOUT, follow_redirects=True, headers={"User-Agent": _URL_UA}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"链接下载失败: {exc}") from exc

    if len(data) > parser.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="链接内容过大，超过 10MB 上限")

    filename = _filename_from_url(url, content_type)
    return _process(filename, data)
