"""消息转换与附件组装。

从 streaming.py 拆出（该文件已超 300 行，coding.md 要求拆模块且不得再增长）：
- message_to_dict：LangChain 消息 → 前端可用的 {role, content, usage?, images?}；
- split_attachments / build_attachment_messages：附件 → 注入用 SystemMessage。
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import SystemMessage

from backend.agent.context import extract_image_urls, extract_text_content
from backend.files.image import ocr_image
from backend.files.parser import MAX_CONTENT_CHARS

logger = logging.getLogger(__name__)


def message_to_dict(m) -> dict | None:
    """把 LangChain 消息对象转成前端可用的 {role, content, usage?, images?}。

    工具调用相关的中间消息不展示：tool 消息、以及仅包含 tool_calls 没有正文的 assistant 消息。
    assistant 消息若携带 usage_metadata，则附上 token 用量，供前端刷新后仍能展示。
    多模态消息中的图片单独提取为 images 数组，供前端在气泡里渲染。
    """
    if m.type in ("system", "tool"):
        return None
    content = extract_text_content(m.content, mark_images=False)
    if m.type == "ai" and getattr(m, "tool_calls", None) and not content.strip():
        return None
    role = {"human": "user", "ai": "assistant"}.get(m.type, m.type)
    images = extract_image_urls(m.content)
    if role not in ("user", "assistant") or (not content and not images):
        return None
    result = {"role": role, "content": content}
    if images:
        result["images"] = images
    attach_names = (getattr(m, "additional_kwargs", None) or {}).get("attachment_names") or []
    if attach_names:
        result["attachments"] = attach_names
    usage_metadata = getattr(m, "usage_metadata", None)
    if usage_metadata:
        try:
            result["usage"] = {
                "input_tokens": usage_metadata.get("input_tokens", 0),
                "output_tokens": usage_metadata.get("output_tokens", 0),
                "total_tokens": usage_metadata.get("total_tokens", 0),
            }
        except Exception:
            pass
    return result


def split_attachments(
    attachments: list,
) -> tuple[list[SystemMessage], list[tuple[str, str]], list[str]]:
    """把附件拆成三类，返回 (文本系统消息列表, 图片列表[(文件名, data_url)], 附件名列表)。

    - 文本附件 → SystemMessage（正文不进入用户气泡，历史回显时被过滤）；
    - 图片附件 → 只收集 data URL，OCR 延迟到发送时再执行。
    """
    text_msgs: list[SystemMessage] = []
    images: list[tuple[str, str]] = []
    names: list[str] = []
    for i, att in enumerate(attachments, 1):
        file_type = getattr(att, "file_type", None) or "text"
        filename = getattr(att, "filename", None) or "未命名文件"
        names.append(filename)

        if file_type == "image":
            data_url = getattr(att, "image", None) or ""
            if data_url:
                images.append((filename, data_url))
        else:
            content = getattr(att, "content", None) or ""
            # 后端兜底截断，防止绕过前端直接提交超长内容
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS] + "\n...[内容过长已截断]"
            text_msgs.append(
                SystemMessage(
                    content=(
                        f"[附件 {i}] 用户上传了文件《{filename}》，其解析后的纯文本内容如下，"
                        f"请结合这些内容回答用户问题：\n\n{content}"
                    )
                )
            )
    return text_msgs, images, names


async def build_attachment_messages(
    attachments: list, api_key: str
) -> tuple[list[SystemMessage], list[str], list[str]]:
    """把附件组装成注入用消息：文本正文 + 图片 OCR 文字。

    Returns:
        (注入用 SystemMessage 列表, 图片 data URL 列表, 附件名列表)。
    OCR 延迟到用户真正发送时才执行，避免上传时无谓调用模型。
    """
    text_msgs, images, names = split_attachments(attachments)
    msgs: list[SystemMessage] = list(text_msgs)
    image_urls = [url for _, url in images]
    if images:
        ocr_results = await asyncio.gather(
            *(ocr_image(url, api_key) for _, url in images),
            return_exceptions=True,
        )
        for (img_name, _), result in zip(images, ocr_results):
            if isinstance(result, BaseException):
                logger.warning("图片 OCR 失败 %s: %s", img_name, result)
                continue
            if result:
                msgs.append(
                    SystemMessage(
                        content=(
                            f"[图片] 图片《{img_name}》经 OCR 提取的文字如下，"
                            f"请结合图片与这段文字回答用户问题：\n\n{result}"
                        )
                    )
                )
    return msgs, image_urls, names
