"""飞书 CLI 工具：让 Agent 通过 lark-cli 操作飞书全业务域。

system prompt 只注入短目录（domain 路由表）；具体子命令由模型按需调用
lark_cli("<domain> --help") 获取，避免每轮携带完整 skill 说明书。
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import shutil

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_LARK_CLI = shutil.which("lark-cli")

# skill 名 → lark-cli domain；不在表内的 skill 不进短目录（认证/工作流等）
_DOMAIN_MAP = {
    "lark-im": "im",
    "lark-calendar": "calendar",
    "lark-doc": "docs",
    "lark-drive": "drive",
    "lark-sheets": "sheets",
    "lark-base": "base",
    "lark-task": "task",
    "lark-mail": "mail",
    "lark-approval": "approval",
    "lark-okr": "okr",
    "lark-wiki": "wiki",
    "lark-contact": "contact",
    "lark-slides": "slides",
    "lark-whiteboard": "whiteboard",
    "lark-minutes": "minutes",
    "lark-note": "note",
    "lark-vc": "vc",
    "lark-attendance": "attendance",
    "lark-markdown": "markdown",
    "lark-apps": "apps",
    "lark-event": "event",
}


def is_available() -> bool:
    """检查 lark-cli 是否已安装。"""
    return _LARK_CLI is not None


async def _run(args: list[str], timeout: float = 60) -> str:
    """执行 lark-cli 子进程并返回输出。"""
    proc = await asyncio.create_subprocess_exec(
        _LARK_CLI, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "Error: lark-cli 命令执行超时"

    out = stdout.decode().strip() if stdout else ""
    err = stderr.decode().strip() if stderr else ""

    if proc.returncode != 0:
        return f"Error (exit {proc.returncode}): {err or out}"
    return out if out else err


def _brief_purpose(desc: str, limit: int = 18) -> str:
    """把 skill 描述压成一行用途：优先取标题（冒号前），否则截断。"""
    text = desc.strip().splitlines()[0]
    for sep in ("。", "；", ";", "：", ":"):
        idx = text.find(sep)
        if 0 < idx <= limit:
            return text[:idx]
    return text[:limit]


async def load_skill_descriptions() -> str:
    """加载飞书 domain 列表（纯数据行），头部模板在 prompts.py 中定义。

    返回形如 '- approval: 飞书审批\\n- apps: 妙搭...' 的多行字符串，
    由 graph.py 使用 LARK_SECTION.format(domain_list=...) 组装完整段落。
    """
    if not is_available():
        return ""
    try:
        raw = await _run(["skills", "list"])
        data = json.loads(raw)
        skills = data.get("skills", [])
        if not skills:
            return ""

        lines = []
        for s in skills:
            name = s.get("name", "")
            domain = _DOMAIN_MAP.get(name)
            if not domain:
                continue
            desc = s.get("description", "") or domain
            lines.append(f"- {domain}: {_brief_purpose(desc)}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("加载 lark-cli skill 描述失败: %s", e)
        return ""


@tool
async def lark_cli(command: str) -> str:
    """执行飞书 CLI 命令。不确定子命令名时，必须先把 command 设为 "<domain> --help"。

    Args:
        command: 不含 'lark-cli' 前缀。例如:
                 'docs --help' 查看文档域子命令,
                 'docs +fetch --doc "<URL或token>" --doc-format markdown' 读取文档,
                 'calendar +agenda' 查看今日日程,
                 'task +get-my-tasks' 查看待办。
    """
    if not is_available():
        return "Error: lark-cli 未安装，请先运行 npm install -g @larksuite/cli"

    logger.info("[LarkCLI] 执行命令: lark-cli %s", command)

    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()

    result = await _run(args)
    logger.info("[LarkCLI] 返回(前500字): %s", result[:500])
    return result
