"""文件上传解析包：把上传的常见文档/表格解析成纯文本，供对话附件使用。"""
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
]
