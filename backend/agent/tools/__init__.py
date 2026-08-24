"""Agent 工具注册表。

新增工具：在本包新建模块，再把 @tool 函数加入 TOOLS。
graph.py 只从这里 import TOOLS，不直接依赖具体工具文件。
"""
from backend.agent.tools.weather import get_weather
from backend.agent.tools.browser_use import browser_fetch, browser_search
from backend.agent.tools.lark_cli import lark_cli, is_available as lark_cli_available

TOOLS = [
    get_weather,
    browser_fetch,
    browser_search,
]

# lark-cli 已安装时自动注册
if lark_cli_available():
    TOOLS.append(lark_cli)

