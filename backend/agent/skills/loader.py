"""技能文件加载：按名读 SKILL.md 正文或 references 下的参考文件，含路径安全校验。

read_skill 是只读入口：本模块绝不执行 skill 声明的任何二进制（metadata.requires.bins），
那类副作用仍由现有工具（lark_cli / browser_*）在既有安全闸门内完成。
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend.agent.skills.registry import get_skill_index, strip_frontmatter

logger = logging.getLogger(__name__)

# ref_path 不允许以这些前缀开头（绝对路径 / 家目录 / Windows 盘符反斜杠）。
_FORBIDDEN_PREFIXES = ("/", "~", "\\")


def _is_unsafe_ref(ref_path: str) -> bool:
    """ref_path 是否构成越界风险：绝对路径、~ 前缀、任一路径节为 '..'。"""
    if not ref_path:
        return False
    if ref_path.startswith(_FORBIDDEN_PREFIXES):
        return True
    parts = ref_path.replace("\\", "/").split("/")
    return any(p == ".." for p in parts)


def resolve_within(root: Path, rel: str) -> Path:
    """把相对路径解析到 root 内；解析后仍不在 root 内则抛 ValueError（含符号链接逃逸）。"""
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / rel).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"路径越界: {rel}")
    return candidate


def load_skill_doc(name: str) -> str:
    """读取指定 skill 的 SKILL.md 正文（剥掉 frontmatter）。"""
    entry = get_skill_index().get(name)
    if entry is None:
        return f"未找到名为 '{name}' 的 skill。可用 skill 见系统提示中的「本地 Skill 目录」。"
    try:
        text = entry.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"读取 skill '{name}' 失败: {e}"
    body = strip_frontmatter(text).strip()
    if not body:
        body = f"skill '{name}' 正文为空。"
    # 附上 skill 目录绝对路径：模型据此定位 scripts/、写 content 文件、跑渲染脚本。
    return f"skill 目录: {entry.path.parent}\n\n{body}"


def load_skill_ref(name: str, ref_path: str) -> str:
    """读取 skill 目录内某份参考文件（如 references/xxx.md）。

    先校验 ref_path（不依赖索引，快速拒绝越界），再定位 skill 目录并做 resolve() 兜底。
    """
    if _is_unsafe_ref(ref_path):
        return "ref_path 必须是 skill 目录内的相对路径（如 references/xxx.md），拒绝绝对路径与 '..'。"

    entry = get_skill_index().get(name)
    if entry is None:
        return f"未找到名为 '{name}' 的 skill。"
    try:
        target = resolve_within(entry.path.parent, ref_path)
    except ValueError as e:
        return f"路径越界被拒绝: {e}"
    if not target.is_file():
        return f"参考文件不存在: {ref_path}"
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"读取参考文件失败: {e}"
