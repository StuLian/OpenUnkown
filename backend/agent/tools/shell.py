"""受控通用命令执行工具：run_command + 命令风险分级。

背景：本地 skill（SKILL.md）是说明书，真正执行依赖「跑命令」（lark-cli / npx / python 等）。
本模块提供**一个**通用 shell 工具，替代「每类命令一个专用工具」，与 Claude/Codex 的通用 Bash 同构。

安全模型（v1，不做 OS 沙箱）：
- 风险分级：只读命令直接放行；写/未知命令默认「write」→ 经 graph.py 的 interrupt() 弹确认卡片；
- **shell 运算符/重定向（&& ; | > < & $() 反引号 换行）一律按「write」需确认**，防止 `ls --help && rm` 绕过；
- `lark-cli` 前缀命令复用 `lark_cli.classify_risk` 的权威 `--help` `Risk:` 信号（含 high-risk-write）；
- 超时 + 输出长度上限 + 固定 cwd + 最小化环境变量（不泄露密钥），失败降级为字符串不抛异常。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
from pathlib import Path

from langchain_core.tools import tool

from backend.agent.tools.lark_cli import classify_risk as _lark_classify

logger = logging.getLogger(__name__)

# 命令执行超时（秒）与输出长度上限（字符），防止长跑/超大输出拖垮一轮对话。
_TIMEOUT = 60
_MAX_OUTPUT = 20000

# 固定 cwd：项目根目录，使 lark-cli 等以稳定 CWD 为基准、写文件可预期。
# 【推理生成】未接入 config，按文件相对定位；shell.py 位于 backend/agent/tools/ 下，parents[3] 即项目根。
_CWD = Path(__file__).resolve().parents[3]

# 只读命令白名单：高置信无副作用的二进制，其余一律按「写」处理需确认（默认拒绝）。
# 注意：`env` 会 dump 环境变量，不进白名单（且 _run_shell 已最小化 env，双重防护）。
# 【推理生成】白名单为保守枚举，宁可多确认、不静默放行。
_READ_ONLY_BINS = frozenset({
    "ls", "cat", "head", "tail", "wc", "grep", "pwd", "echo", "date",
    "which", "ps", "df", "du", "uname", "file", "diff", "sort",
    "uniq", "man", "id", "whoami", "hostname",
})

# 显式只读标志：仅当命令不含 shell 运算符时才视为无副作用（--help/--version/--dry-run）。
_READ_ONLY_FLAGS = {"--help", "-h", "--version", "--dry-run"}

# shell 运算符/重定向/替换符：出现即无法保证「单命令只读」，一律按「写」需确认。
# 覆盖 && || ; | > < & $( ) 反引号 与换行（`>>` 含 `>`、`2>` 含 `>`，均已覆盖）。
_SHELL_META = ("&&", "||", ";", "|", ">", "<", "&", "$(", "`", "\n", "\r")

# 最小化子进程环境：只透传执行命令必需的键，不泄露 ApiKey/Token 等敏感环境变量。
_MIN_ENV_KEYS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "USER", "LOGNAME",
    "TMPDIR", "TMP", "TEMP", "TERM", "COLORTERM", "PWD", "HOSTNAME",
)


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    """超长输出截断，防止超大命令结果拖垮一轮对话。"""
    if len(text) > limit:
        return text[:limit] + "\n…（输出已截断）"
    return text


def _has_shell_meta(command: str) -> bool:
    """命令是否含 shell 运算符/重定向/替换符：含则无法保证只读，须按写确认。"""
    return any(m in command for m in _SHELL_META)


def _classify_generic(args: list[str]) -> str:
    """非 lark-cli 命令的风险判定：显式只读标志或只读二进制 → read，其余一律 write（默认拒绝）。"""
    if any(a in _READ_ONLY_FLAGS for a in args):
        return "read"
    if args[0] in _READ_ONLY_BINS:
        return "read"
    return "write"


async def classify_command_risk(command: str) -> str:
    """通用命令风险分级：lark-cli 前缀走权威 --help 信号，其余走白名单 + 默认拒绝。

    返回 read / write / high-risk-write。lark-cli 才可能出现 high-risk-write（需 --yes），
    通用命令最高只到 write。含 shell 运算符/重定向的一律判 write（需确认）。
    """
    if _has_shell_meta(command):
        return "write"
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    if not args:
        return "read"
    if args[0] == "lark-cli":
        sub = command.strip()
        if sub.lower().startswith("lark-cli"):
            sub = sub[len("lark-cli"):].strip()
        return await _lark_classify(sub)
    return _classify_generic(args)


def _minimal_env() -> dict[str, str]:
    """构造最小化子进程环境，避免 ApiKey/Token 等敏感环境变量被命令 dump 或外泄。"""
    return {k: v for k, v in os.environ.items() if k in _MIN_ENV_KEYS}


async def _run_shell(command: str) -> str:
    """执行 shell 命令（经 /bin/sh -c，支持管道/重定向），合并 stdout/stderr，超时/超长截断。"""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(_CWD),
            env=_minimal_env(),
        )
    except Exception as e:  # noqa: BLE001
        return f"Error: 启动命令失败: {e}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return "Error: 命令执行超时（已终止）"

    text = out.decode(errors="replace").strip() if out else ""
    text = _truncate(text)
    if proc.returncode != 0:
        return f"Error (exit {proc.returncode}): {text}"
    return text or "(命令执行成功，无输出)"


@tool
async def run_command(command: str) -> str:
    """执行一条 shell 命令并返回输出。用于执行本地 skill 说明书里要求的命令（如 lark-cli、npx）。

    只读命令直接执行；写操作或无法判定风险的命令，系统会先弹出确认卡片，经用户批准后才真正执行，
    你无需自行判断或拦截。不确定命令名/参数时，先 `--help` 查看用法，不要臆造。

    Args:
        command: 完整 shell 命令，例如 'lark-cli docs --help'、'npx skills find react'。
    """
    logger.info("[Shell] 执行命令: %s", command)
    result = await _run_shell(command)
    logger.info("[Shell] 返回(前300字): %s", result[:300])
    return result
