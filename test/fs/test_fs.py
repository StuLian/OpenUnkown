"""文件系统工具测试：路径安全 + 读写 + list_files。

把 fs 工具的根临时指向 tmp_path（monkeypatch），避免污染仓库。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent.tools import fs


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    """把 fs 工具的可访问根临时指到 tmp_path。"""
    monkeypatch.setattr(fs, "_WORKSPACE", tmp_path)
    monkeypatch.setattr(fs, "_READ_ROOTS", (tmp_path,))
    monkeypatch.setattr(fs, "_WRITE_ROOTS", (tmp_path,))
    return tmp_path


def _outside_dir(tmp_path) -> Path:
    """构造一个不在允许根（tmp_path）内的目录。"""
    d = tmp_path.parent / "outside-fs-test"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_resolve_rejects_traversal(scoped):
    with pytest.raises(ValueError):
        fs._resolve("../etc/passwd", fs._READ_ROOTS)


def test_resolve_rejects_absolute_escape(scoped, tmp_path):
    outside = _outside_dir(tmp_path) / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        fs._resolve(str(outside), fs._READ_ROOTS)


def test_resolve_rejects_symlink_escape(scoped, tmp_path):
    outside = _outside_dir(tmp_path) / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "evil"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")
    with pytest.raises(ValueError):
        fs._resolve(str(link), fs._READ_ROOTS)


def test_write_read_roundtrip(scoped):
    out = fs.write_file.invoke({"path": "data/content.json", "content": '{"a": 1}'})
    assert "已写入" in out
    assert fs.read_file.invoke({"path": "data/content.json"}) == '{"a": 1}'


def test_list_files(scoped):
    fs.write_file.invoke({"path": "a.txt", "content": "hi"})
    fs.write_file.invoke({"path": "sub/b.txt", "content": "hi"})
    listing = fs.list_files.invoke({"path": "."})
    assert "a.txt" in listing
    assert "sub/" in listing


def test_write_outside_rejected(scoped):
    out = fs.write_file.invoke({"path": "/etc/pwned.txt", "content": "x"})
    assert "越界" in out


def test_write_rejects_skills_dir_but_read_allows(scoped, tmp_path, monkeypatch):
    """skills 目录可读但不可写（防覆写 SKILL.md 持久化注入）。"""
    skills = tmp_path.parent / "fake-skills"
    skills.mkdir(exist_ok=True)
    monkeypatch.setattr(fs, "_READ_ROOTS", (tmp_path, skills))
    monkeypatch.setattr(fs, "_WRITE_ROOTS", (tmp_path,))
    # 写 skills 目录被拒
    out = fs.write_file.invoke({"path": str(skills / "SKILL.md"), "content": "evil"})
    assert "越界" in out
    # 读 skills 目录允许
    (skills / "SKILL.md").write_text("ok", encoding="utf-8")
    assert fs.read_file.invoke({"path": str(skills / "SKILL.md")}) == "ok"


def test_read_nonexistent(scoped):
    assert fs.read_file.invoke({"path": "nope.txt"}) == "文件不存在: nope.txt"
