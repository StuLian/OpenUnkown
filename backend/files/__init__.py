"""文件上传解析包：文档/表格解析为纯文本，图片校验编码与 OCR。"""
from backend.files.image import (
    IMAGE_EXTENSIONS,
    MAX_IMAGE_SIZE,
    ImageError,
    ImageFile,
    ocr_image,
    process_image,
)
from backend.files.parser import (
    ALLOWED_EXTENSIONS,
    MAX_CONTENT_CHARS,
    MAX_FILE_SIZE,
    ParseError,
    ParsedFile,
    parse_bytes,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_CONTENT_CHARS",
    "MAX_FILE_SIZE",
    "ParseError",
    "ParsedFile",
    "parse_bytes",
    "IMAGE_EXTENSIONS",
    "MAX_IMAGE_SIZE",
    "ImageError",
    "ImageFile",
    "process_image",
    "ocr_image",
]
