"""lark-cli 命令风险分级工具函数（供 shell.bash 复用）。

原 `lark_cli` 独立工具已退役：飞书操作改由通用 `bash("lark-cli ...")` 承接，
本模块只保留「判定一条 lark-cli 命令是读还是写」的分级逻辑。

风险分级权威信号：lark-cli 每条命令的 `--help` 都带一行 `Risk: read | write | high-risk-write`，
以它为准并缓存；判定不了时兜底为 write（宁可多确认一次，也不静默写入）。
"""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
import shutil

logger = logging.getLogger(__name__)

_LARK_CLI = shutil.which("lark-cli")

# 只读 domain：CLI 管理类域名不改飞书业务数据。
_READ_ONLY_DOMAINS = frozenset({
    "skills", "schema", "help", "doctor", "config", "profile", "auth", "update",
})
_RISK_CACHE: dict[str, str] = {}
_RISK_RE = re.compile(
    r"^\s*Risk:\s*(read|write|high-risk-write)\b", re.IGNORECASE | re.MULTILINE
)


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


def _command_key(args: list[str]) -> tuple[str, list[str]]:
    """从命令 token 里提取定位命令身份的 key（去掉参数与取值）。

    例如 'im +messages-send --chat-id oc_xxx --text hi' -> ('im +messages-send', ['im', '+messages-send'])；
    'im messages delete --message-id om_xxx' -> ('im messages delete', ['im', 'messages', 'delete'])。
    """
    if not args:
        return "", []
    domain = args[0].lower()
    if domain == "api":
        method = (args[1] if len(args) > 1 else "").upper()
        return f"api:{method}", ["api", method]
    tokens = [domain]
    for tok in args[1:]:
        if tok.startswith("-"):
            break
        tokens.append(tok)
    return " ".join(tokens), tokens


async def _risk_from_help(key_tokens: list[str]) -> str:
    """用 '<domain> <subcommand> --help' 拉取权威 Risk 分级。"""
    try:
        out = await _run([*key_tokens, "--help"], timeout=25)
    except Exception as e:  # noqa: BLE001
        logger.warning("[LarkCLI] 读取 %s --help 失败: %s", " ".join(key_tokens), e)
        return "unknown"
    m = _RISK_RE.search(out)
    if m:
        return m.group(1).lower()
    return "unknown"


async def classify_risk(command: str) -> str:
    """判定 lark-cli 命令风险级别：read / write / high-risk-write。

    command 不含 'lark-cli' 前缀（如 'docs +fetch --doc ...'）。
    - read：只读，直接放行；
    - write / high-risk-write：会改动飞书数据，执行前需用户确认；
    - 判定失败兜底为 write（需要确认）。
    """
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()
    if not args:
        return "read"

    domain = args[0].lower()
    # --help / --dry-run 不会产生任何副作用
    if any(a in ("--help", "-h", "--dry-run") for a in args):
        return "read"
    # CLI 管理类域名不改飞书业务数据
    if domain in _READ_ONLY_DOMAINS:
        return "read"
    # api 裸调用按 HTTP 方法区分
    if domain == "api":
        method = (args[1] if len(args) > 1 else "").upper()
        return "read" if method == "GET" else "write"

    key, key_tokens = _command_key(args)
    if key in _RISK_CACHE:
        return _RISK_CACHE[key]

    risk = await _risk_from_help(key_tokens)
    if risk == "unknown":
        risk = "write"  # 未知一律视为写，需要确认，绝不静默放行
    _RISK_CACHE[key] = risk
    return risk


def ensure_yes(command: str) -> str:
    """high-risk-write 经用户确认后补上 --yes，让 lark-cli 真正执行。

    lark-cli 的约定是「agent 不得自行加 --yes，只能在用户确认后加」；本项目的用户
    确认由 graph.py 的 interrupt 完成，确认通过后这里补 --yes 即等价于用户授权。
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if "--yes" in tokens:
        return command
    return command.rstrip() + " --yes"
