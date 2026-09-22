"""本地 skill 加载器测试：frontmatter 解析、正文剥离、目录扫描、路径安全。

不依赖真实 ~/.agents/skills/：扫描与路径安全用例均使用临时目录（tmp_path）。
"""
from __future__ import annotations

import pytest

from backend.agent.skills.loader import load_skill_ref, resolve_within
from backend.agent.skills.registry import (
    build_directory,
    parse_frontmatter,
    scan_skills,
    strip_frontmatter,
)

# 一份带 metadata 块的典型 frontmatter（描述为整体引号包裹、含全角冒号）。
_QUOTED_FM = """---
name: lark-doc
description: "飞书云文档内容操作：读取、创建、编辑文档。"
metadata:
  requires:
    bins: ["lark-cli"]
  cliHelp: "lark-cli docs --help"
---

# docs

正文内容，不含 frontmatter。
"""

# find-skills 风格：描述未加引号，且内部含半角双引号。
_UNQUOTED_FM = """---
name: find-skills
description: Helps discover skills when users ask "how do I do X".
---

# Find Skills

正文。
"""


def _write_skill(root, name, content):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def _seed_two_skills(root):
    """写入 ai-daily-report（未引号描述）与 lark-doc（引号描述），返回根目录。"""
    _write_skill(root, "ai-daily-report", _UNQUOTED_FM.replace("find-skills", "ai-daily-report"))
    _write_skill(root, "lark-doc", _QUOTED_FM)
    return root


def test_parse_frontmatter_quoted_description():
    name, desc = parse_frontmatter(_QUOTED_FM)
    assert name == "lark-doc"
    # 外层引号被剥去，内部全角冒号保留
    assert desc == "飞书云文档内容操作：读取、创建、编辑文档。"


def test_parse_frontmatter_unquoted_with_inner_quotes():
    name, desc = parse_frontmatter(_UNQUOTED_FM)
    assert name == "find-skills"
    # 整体未包裹引号，不剥；内部半角引号原样保留
    assert desc == 'Helps discover skills when users ask "how do I do X".'


def test_parse_frontmatter_missing_returns_none():
    name, desc = parse_frontmatter("# 无 frontmatter\n\n正文")
    assert name is None
    assert desc is None


def test_strip_frontmatter_keeps_body():
    body = strip_frontmatter(_QUOTED_FM).strip()
    assert body.startswith("# docs")
    assert "正文内容" in body
    assert "name: lark-doc" not in body


def test_parse_frontmatter_block_scalar_description():
    # lark-whiteboard 风格：description 用折行块标量 '>'，后续缩进行合并成一段
    fm = """---
name: lark-whiteboard
version: 1.0.0
description: >
  飞书画板：查询和编辑飞书云文档中的画板。
  当用户需要查看画板内容时使用此 skill。
metadata:
  requires:
    bins: ["lark-cli"]
---

正文。
"""
    name, desc = parse_frontmatter(fm)
    assert name == "lark-whiteboard"
    assert desc == "飞书画板：查询和编辑飞书云文档中的画板。 当用户需要查看画板内容时使用此 skill。"


def test_scan_skills_includes_nonlark_and_skips_broken(tmp_path):
    _seed_two_skills(tmp_path)
    # 缺 name 的 SKILL.md 应被跳过
    _write_skill(tmp_path, "broken", "---\ndescription: 缺 name\n---\n正文")
    # 无 SKILL.md 的目录应被跳过
    (tmp_path / "empty-dir").mkdir()

    index = scan_skills(tmp_path)
    assert set(index.keys()) == {"ai-daily-report", "lark-doc"}
    assert index["lark-doc"].description == "飞书云文档内容操作：读取、创建、编辑文档。"


def test_build_directory_one_line_per_skill(tmp_path):
    index = scan_skills(_seed_two_skills(tmp_path))
    text = build_directory(index)
    lines = text.splitlines()
    assert len(lines) == len(index)
    assert any(line.startswith("- ai-daily-report: ") for line in lines)
    assert any(line.startswith("- lark-doc: ") for line in lines)


def test_resolve_within_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "../etc/passwd")


def test_resolve_within_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    link = skill_dir / "evil"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")
    with pytest.raises(ValueError):
        resolve_within(skill_dir, "evil")


def test_load_skill_ref_rejects_traversal_without_touching_real_dir():
    # 越界 ref_path 应在索引查找前被快速拒绝（不会扫描真实 SKILLS_DIR）
    out = load_skill_ref("whatever", "../etc/passwd")
    assert "ref_path 必须" in out


def test_load_skill_ref_absolute_path_rejected():
    out = load_skill_ref("whatever", "/etc/passwd")
    assert "ref_path 必须" in out
