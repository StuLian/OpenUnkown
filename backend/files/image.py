"""图片附件的处理：校验、缩放、编码为 data URL，以及基于多模态模型的 OCR。

图片是二进制像素数据，无法像文档一样直接「解析成文字」，这里做两件事：
1. 用 Pillow 校验图片、限制长边尺寸后编码为 data URL，供前端预览与模型看图；
2. OCR：调用视觉模型把图片中的文字提取为文本，作为附件文字参与问答。
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from backend.config import DEFAULT_PLATFORM, VISION_MODEL, get_platform

# 支持的图片扩展名（不含点）
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")

# 单张图片大小上限（字节）
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
# 图片长边上限（像素），超出等比缩小，控制 base64 体积与模型输入
MAX_IMAGE_EDGE = 2048
# OCR 调用超时（秒）
OCR_TIMEOUT = 60.0
# OCR 返回文本的长度上限（字符）
OCR_MAX_CHARS = 20_000

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

_OCR_PROMPT = (
    "请完整提取这张图片中的所有文字，只输出文字本身，"
    "保留原有段落与换行，不要添加任何解释或前后缀。"
    "如果图中没有可识别的文字，只输出「(无文字)」。"
)


class ImageError(Exception):
    """图片处理失败（格式不支持 / 内容损坏 / 超出限制）。"""


@dataclass
class ImageFile:
    """单张图片处理结果。"""

    filename: str
    mime: str
    width: int
    height: int
    size: int        # 处理后字节数
    data_url: str    # data:<mime>;base64,...


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def image_extension(filename: str) -> str:
    """归一化图片扩展名；非图片扩展名抛出 ImageError。"""
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "jpeg" if ext == "jpg" else ext
    raise ImageError(
        f"不支持的图片格式「.{ext or '?'}」，仅支持：{', '.join(IMAGE_EXTENSIONS)}"
    )


def process_image(filename: str, data: bytes) -> ImageFile:
    """校验并编码图片：限制尺寸后转成 data URL。"""
    if not data:
        raise ImageError("图片内容为空")
    if len(data) > MAX_IMAGE_SIZE:
        raise ImageError(
            f"图片过大（{_fmt_size(len(data))}），上限 {_fmt_size(MAX_IMAGE_SIZE)}"
        )

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ImageError("缺少图片处理依赖 Pillow，请安装后重试") from exc

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ImageError("图片无法解析（文件可能已损坏或格式不符）") from exc

    # GIF 等多帧图只取第一帧
    try:
        img.seek(0)
    except Exception:  # noqa: BLE001
        pass

    # 统一转 RGB / RGBA，便于按有无透明通道选择编码格式
    if img.mode not in ("RGB", "RGBA"):
        if "A" in img.getbands():
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

    # 长边超过上限时等比缩小
    if max(img.size) > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / max(img.size)
        new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        img = img.resize(new_size)

    # 有透明通道用 PNG，否则用 JPEG（体积更小，视觉模型普遍支持）
    if img.mode == "RGBA":
        out_mime = "image/png"
        out_fmt = "PNG"
    else:
        out_mime = "image/jpeg"
        out_fmt = "JPEG"

    buf = io.BytesIO()
    img.save(buf, format=out_fmt, quality=90)
    payload = buf.getvalue()

    data_url = f"data:{out_mime};base64," + base64.b64encode(payload).decode("ascii")
    return ImageFile(
        filename=(filename or "").rsplit("/", 1)[-1] or "未命名图片",
        mime=out_mime,
        width=img.width,
        height=img.height,
        size=len(payload),
        data_url=data_url,
    )


async def ocr_image(data_url: str, api_key: str) -> str:
    """调用视觉模型提取图片文字，返回纯文本（异步，发送时调用）。"""
    if not api_key:
        raise ImageError("未配置模型服务 ApiKey，无法执行 OCR")
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise ImageError("缺少 langchain 依赖，无法执行 OCR") from exc

    llm = ChatOpenAI(
        model=VISION_MODEL,
        api_key=api_key,
        base_url=get_platform(DEFAULT_PLATFORM)["base_url"],
        temperature=0,
        max_tokens=2000,
        request_timeout=OCR_TIMEOUT,
    )
    resp = await llm.ainvoke(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
            )
        ]
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content or "")
    text = text.strip()
    if not text:
        return "(无文字)"
    if len(text) > OCR_MAX_CHARS:
        text = text[:OCR_MAX_CHARS] + "\n...[OCR 文本过长已截断]"
    return text
