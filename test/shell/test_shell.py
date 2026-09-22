"""受控通用执行工具测试：命令风险分级、输出截断、ensure_yes。

不依赖真实 lark-cli / npx：lark 委托用 monkeypatch 打桩，其余只测纯逻辑。
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.tools import shell
from backend.agent.tools.lark_cli import ensure_yes


def _run(coro):
    return asyncio.run(coro)


def test_classify_read_only_bin():
    assert _run(shell.classify_command_risk("ls -la")) == "read"
    assert _run(shell.classify_command_risk("cat /etc/hosts")) == "read"


def test_classify_help_flag_is_read():
    assert _run(shell.classify_command_risk("curl --help")) == "read"
    assert _run(shell.classify_command_risk("git --version")) == "read"


def test_classify_unknown_defaults_to_write():
    # npx / rm / python 均不在只读白名单 → 默认按写，需确认
    assert _run(shell.classify_command_risk("npx skills find react")) == "write"
    assert _run(shell.classify_command_risk("rm -rf /tmp/x")) == "write"
    assert _run(shell.classify_command_risk("python render.py")) == "write"


def test_classify_empty_command_is_read():
    assert _run(shell.classify_command_risk("")) == "read"


def test_classify_shell_operator_forces_write():
    # shell 运算符/重定向不得被 --help 或白名单二进制误判为只读
    assert _run(shell.classify_command_risk("ls --help && rm -rf /tmp/pwned")) == "write"
    assert _run(shell.classify_command_risk("echo pwnd > /tmp/pwned")) == "write"
    assert _run(shell.classify_command_risk("cat /etc/hosts > /tmp/copied")) == "write"
    assert _run(shell.classify_command_risk("pwd; whoami")) == "write"


def test_classify_lark_with_shell_operator_forces_write():
    assert _run(shell.classify_command_risk("lark-cli docs --help && rm -rf /")) == "write"


def test_classify_env_not_read():
    # env 会 dump 环境变量，必须确认，不放行
    assert _run(shell.classify_command_risk("env")) == "write"


def test_minimal_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret-123")
    env = shell._minimal_env()
    assert "DASHSCOPE_API_KEY" not in env
    assert "PATH" in env


def test_classify_lark_delegation_strips_prefix(monkeypatch):
    """lark-cli 前缀命令应剥离前缀后委托给 lark_cli.classify_risk。"""

    async def fake_classify(sub):
        assert sub == "docs create --title x"
        return "high-risk-write"

    monkeypatch.setattr(shell, "_lark_classify", fake_classify)
    assert _run(shell.classify_command_risk("lark-cli docs create --title x")) == "high-risk-write"


def test_truncate_caps_output():
    assert shell._truncate("short") == "short"
    out = shell._truncate("x" * 100, limit=10)
    assert out.startswith("x" * 10)
    assert "截断" in out


def test_ensure_yes_appends_only_once():
    assert ensure_yes("lark-cli docs delete --doc abc") == "lark-cli docs delete --doc abc --yes"
    # 已带 --yes 不再重复
    assert ensure_yes("lark-cli docs delete --doc abc --yes") == "lark-cli docs delete --doc abc --yes"
