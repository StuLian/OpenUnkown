#!/usr/bin/env python3
"""重新生成 AGENTS.md 中的「自动生成区域」。

用法：
    python scripts/gen_agents_doc.py

只重写 AGENTS.md 里由 HTML 注释包裹的区域：

    <!-- AUTO-GEN:NAME -->
    ...
    <!-- /AUTO-GEN:NAME -->

支持的区域：
    DEPS   — 依赖版本（requirements.txt + frontend/package.json）
    ROUTES — 后端 API 路由表（扫描 backend/api/routers/*.py）
    FILES  — 源码文件清单（backend/ 与 frontend/src/ 的目录树）

手写区域（概述、目录地图、约定与坑、维护说明）不受影响。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
ROUTERS_DIR = ROOT / "backend" / "api" / "routers"


def _replace_region(text: str, name: str, body: str) -> tuple[str, int]:
    """替换单个 AUTO-GEN 区域的内容，返回 (新文本, 命中次数)。"""
    pattern = re.compile(
        rf"(<!-- AUTO-GEN:{name} -->)(.*?)(<!-- /AUTO-GEN:{name} -->)", re.DOTALL
    )
    new_block = f"<!-- AUTO-GEN:{name} -->\n{body.strip()}\n<!-- /AUTO-GEN:{name} -->"
    new_text, n = pattern.subn(lambda m: new_block, text)
    return new_text, n


def gen_deps() -> str:
    """依赖版本：requirements.txt 全文 + package.json 关键依赖。"""
    lines: list[str] = ["**后端（`requirements.txt`）**：", "", "```"]
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    lines.append("```")

    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    dep_str = ", ".join(f"{k} {v}" for k, v in sorted(pkg.get("dependencies", {}).items()))
    dev_str = ", ".join(f"{k} {v}" for k, v in sorted(pkg.get("devDependencies", {}).items()))
    lines += ["", f"**前端 dependencies**：{dep_str}", f"**前端 devDependencies**：{dev_str}"]
    return "\n".join(lines)


def gen_routes() -> str:
    """扫描 routers 目录，生成 API 路由表。"""
    rows: list[tuple[str, str, str, str]] = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r'APIRouter\(\s*prefix="([^"]+)"', text)
        prefix = m.group(1) if m else "(none)"
        routes = re.findall(
            r'@router\.(get|post|put|delete|patch)\(["\']([^"\']*)["\']', text
        )
        for method, route in routes:
            route_display = route if route else "(空)"
            rows.append((prefix, method.upper(), route_display, path.name))

    header = "| 前缀 | 方法 | 路径 | 文件 |\n|------|------|------|------|"
    body = "\n".join(
        f"| `{prefix}` | {method} | `{route}` | {fname} |"
        for prefix, method, route, fname in rows
    )
    return header + "\n" + body


def _tree(root: Path, prefix: str = "") -> list[str]:
    """递归生成 ASCII 目录树（跳过 __pycache__）。"""
    entries = sorted(
        [p for p in root.iterdir() if p.name != "__pycache__"],
        key=lambda p: (p.is_file(), p.name),
    )
    out: list[str] = []
    for i, p in enumerate(entries):
        last = i == len(entries) - 1
        branch = "└── " if last else "├── "
        child_prefix = prefix + ("    " if last else "│   ")
        if p.is_dir():
            out.append(prefix + branch + p.name + "/")
            out.extend(_tree(p, child_prefix))
        else:
            out.append(prefix + branch + p.name)
    return out


def gen_files() -> str:
    """backend/ 与 frontend/src/ 的源码目录树。"""
    parts = ["```text", "backend/"]
    parts.extend(_tree(ROOT / "backend", "  "))
    parts.append("frontend/src/")
    parts.extend(_tree(ROOT / "frontend" / "src", "  "))
    parts.append("```")
    return "\n".join(parts)


def main() -> int:
    if not AGENTS.exists():
        print(f"未找到 {AGENTS}")
        return 1

    text = AGENTS.read_text(encoding="utf-8")
    for name, gen in (("DEPS", gen_deps), ("ROUTES", gen_routes), ("FILES", gen_files)):
        new_text, n = _replace_region(text, name, gen())
        if n == 0:
            print(f"警告：未找到 AUTO-GEN:{name} 标记，跳过该区域")
        else:
            text = new_text
            print(f"已更新 AUTO-GEN:{name}")

    AGENTS.write_text(text, encoding="utf-8")
    print(f"完成：{AGENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
