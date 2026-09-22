"""通用文件系统工具：read_file / write_file / list_files。

补齐 Claude/Codex 三件套里的「文件系统」一环——本地 skill 往往要「写内容文件 + 读参考 + 跑脚本」，
只靠 bash（shell）与 read_skill（只读 skill 说明书）不够。

安全模型：
- 读/列：可访问「项目 workspace + 本地 skills 目录」；写：**仅 workspace**——skill 目录只读，
  防止 write_file 静默覆写 `~/.agents/skills/*/SKILL.md` 造成跨会话持久化提示注入；
- 路径严格 `resolve()` 包含性校验，`../`/绝对越界/符号链接逃逸全拒；
- 任意命令执行仍走 `bash` 的写操作确认闸门，本工具不执行任何二进制。
"""
from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import tool

from backend.config import SKILLS_DIR

logger = logging.getLogger(__name__)

# 项目 workspace 根：fs.py 位于 backend/agent/tools/ 下，parents[3] 即项目根。
# 【推理生成】按文件相对定位，未接入 config；与 shell.py 的 _CWD 同一推导方式。
_WORKSPACE = Path(__file__).resolve().parents[3]

# 读/列可访问根：项目 workspace + 本地 skills 目录（skill 的 scripts/、references/ 需要被读）。
_READ_ROOTS = (_WORKSPACE, Path(SKILLS_DIR))
# 写可访问根：仅项目 workspace。skill 目录只读——写 SKILL.md/scripts 会把恶意内容持久化注入后续会话。
_WRITE_ROOTS = (_WORKSPACE,)


def _resolve(path: str, roots: tuple[Path, ...]) -> Path:
    """把路径解析到允许的根内；相对路径相对 workspace 根，越界则抛 ValueError。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _WORKSPACE / p
    resolved = p.resolve()
    for root in roots:
        root_r = Path(root).resolve()
        if resolved == root_r or root_r in resolved.parents:
            return resolved
    raise ValueError(f"路径越界: {path}")


@tool
def read_file(path: str) -> str:
    """读取文本文件内容。可读项目 workspace 与本地 skills 目录。

    Args:
        path: 文件路径（相对路径相对项目根，或绝对路径），例如 'data/x.json' 或 '~/.../SKILL.md'。
    """
    try:
        target = _resolve(path, _READ_ROOTS)
    except ValueError as e:
        return f"路径越界被拒绝: {e}"
    if not target.is_file():
        return f"文件不存在: {path}"
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"读取失败: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """把文本内容写入文件（覆盖已有内容，父目录不存在时自动创建）。**仅限项目 workspace 内**，
    不能写本地 skills 目录（skill 说明书只读）。

    Args:
        path: 目标文件路径（相对路径相对项目根，或绝对路径），例如 'content.json'。
        content: 要写入的完整文本内容。
    """
    try:
        target = _resolve(path, _WRITE_ROOTS)
    except ValueError as e:
        return f"路径越界被拒绝（仅允许写入 workspace）: {e}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"写入失败: {e}"
    return f"已写入 {target}（{len(content)} 字符）"


@tool
def list_files(path: str = ".") -> str:
    """列出目录下的文件与子目录（按名排序）。可列项目 workspace 与本地 skills 目录。

    Args:
        path: 目录路径（默认项目根 workspace）。
    """
    try:
        target = _resolve(path, _READ_ROOTS)
    except ValueError as e:
        return f"路径越界被拒绝: {e}"
    if not target.is_dir():
        return f"目录不存在: {path}"
    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name)
    except OSError as e:
        return f"列目录失败: {e}"
    lines = [e.name + ("/" if e.is_dir() else "") for e in entries]
    return "\n".join(lines) if lines else "（空目录）"
