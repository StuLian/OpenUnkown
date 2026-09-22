"""技能注册表：扫描本地 skills 目录，解析 frontmatter，缓存索引并生成目录。

skill 的磁盘形态（实测 ~/.agents/skills/）：
    <skills_dir>/<name>/SKILL.md          # 正文 + YAML frontmatter(name/description/metadata)
    <skills_dir>/<name>/references/*.md   # 惰性参考文件

本项目 requirements.txt 不含 PyYAML，故只手写解析顶层 `name` / `description` 两个
单行标量键，不解析 metadata 块，也不引入新依赖。
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.config import SKILLS_DIR

logger = logging.getLogger(__name__)

# 目录条目每行的 description 截断长度（字符）：压成一句话，控制常驻 prompt 的 token 成本。
_BRIEF_LIMIT = 40

# frontmatter 定界：文件必须以 `---` 行开头，且存在成对的 `---` 行才视为有 frontmatter。
# 【推理生成】delimiter 按所见样本（首行 ---、键值区、再一行 ---）推导，未对全部 skill 校验。
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


@dataclass(frozen=True)
class SkillEntry:
    """一个 skill 的索引条目（只存目录注入所需的最小信息）。"""

    name: str
    description: str
    path: Path  # SKILL.md 绝对路径


def parse_frontmatter(text: str) -> tuple[str | None, str | None]:
    """解析 SKILL.md 的 frontmatter，返回 (name, description)；无 frontmatter 时 name 为 None。

    只认顶层、无缩进的 `name:` / `description:` 行。description 支持三种形态：
    单行标量（可整体加引号）与块标量（`>` / `|`，后续缩进行合并）。metadata 块内的键带缩进，
    直接跳过，避免误判。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, None
    lines = m.group(1).splitlines()
    name: str | None = None
    desc: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line or line[0].isspace():
            i += 1
            continue
        if line.startswith("name:"):
            name = line[len("name:"):].strip()
        elif line.startswith("description:"):
            value = line[len("description:"):].strip()
            if value in (">", "|"):
                # 块标量：收集后续所有缩进行，折行合并为一段（description 只进目录，合并即可）。
                parts: list[str] = []
                j = i + 1
                while j < len(lines) and lines[j] and lines[j][0].isspace():
                    parts.append(lines[j].strip())
                    j += 1
                desc = " ".join(parts)
                i = j
                continue
            desc = value
        i += 1
    if desc is not None:
        desc = _unquote(desc)
    return name, desc


def strip_frontmatter(text: str) -> str:
    """去掉开头的 frontmatter 块，返回正文；无 frontmatter 时原样返回。"""
    m = _FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def _unquote(value: str) -> str:
    """仅当整个值被成对单/双引号包裹时剥去外层引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value


def scan_skills(skills_dir: Path) -> dict[str, SkillEntry]:
    """扫描 skills 目录，返回 name -> SkillEntry 索引；目录缺失/损坏条目降级跳过。"""
    result: dict[str, SkillEntry] = {}
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        logger.warning("[Skills] 目录不存在，跳过扫描: %s", skills_dir)
        return result
    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        md = sub / "SKILL.md"
        if not md.is_file():
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("[Skills] 读取 %s 失败，跳过: %s", md, e)
            continue
        name, desc = parse_frontmatter(text)
        if not name:
            logger.warning("[Skills] %s 缺少 name，跳过", md)
            continue
        result[name] = SkillEntry(name=name, description=desc or "", path=md)
    return result


def build_directory(index: dict[str, SkillEntry]) -> str:
    """把索引组装成注入 prompt 的目录：每行 `- name: 一句话用途`。"""
    lines = []
    for name in sorted(index):
        lines.append(f"- {name}: {_brief(index[name].description)}")
    return "\n".join(lines)


def _brief(desc: str) -> str:
    """把 description 压成一行用途：折叠空白，遇到首个句读符且足够短则截断。"""
    text = " ".join((desc or "").strip().split())
    if not text:
        return ""
    for sep in ("。", "；", ";", "：", ":"):
        idx = text.find(sep)
        if 0 < idx <= _BRIEF_LIMIT:
            return text[:idx]
    return text[:_BRIEF_LIMIT]


def _fingerprint(skills_dir: Path) -> tuple:
    """目录指纹：(skill 名, SKILL.md mtime) 的有序元组；内容或集合变化都会变。

    只 stat 不读文件，30 个 skill 开销可忽略；据此判断是否要重扫缓存。
    """
    if not skills_dir.is_dir():
        return ()
    items = []
    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        md = sub / "SKILL.md"
        if not md.is_file():
            continue
        try:
            items.append((sub.name, md.stat().st_mtime))
        except OSError:
            items.append((sub.name, -1.0))
    return tuple(items)


# 索引缓存：按 (目录路径, 指纹) 缓存；生产只扫 SKILLS_DIR，测试可传临时目录。
_index_cache: dict[str, SkillEntry] | None = None
_cache_key: tuple[str, tuple] | None = None
_lock = threading.Lock()


def get_skill_index(skills_dir: Path | None = None) -> dict[str, SkillEntry]:
    """返回 skill 索引，指纹命中走缓存。skills_dir 为空时用配置的 SKILLS_DIR。"""
    d = Path(skills_dir) if skills_dir is not None else SKILLS_DIR
    fp = _fingerprint(d)
    key = (str(d), fp)
    global _index_cache, _cache_key
    with _lock:
        if _index_cache is not None and _cache_key == key:
            return _index_cache
        idx = scan_skills(d)
        _index_cache = idx
        _cache_key = key
        return idx


def get_skill_directory(skills_dir: Path | None = None) -> str:
    """生成注入 prompt 的 skill 目录；目录为空时返回空串（调用方决定是否注入）。"""
    return build_directory(get_skill_index(skills_dir))
