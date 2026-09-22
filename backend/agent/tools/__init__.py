"""Agent 工具注册表。

新增工具：在本包新建模块，再把 @tool 函数加入 TOOLS。
graph.py 只从这里 import TOOLS，不直接依赖具体工具文件。
"""
from backend.agent.tools.weather import get_weather
from backend.agent.tools.browser_use import browser_fetch, browser_search
from backend.agent.tools.hotels import search_hotels
from backend.agent.tools.shell import run_command

TOOLS = [
    get_weather,
    browser_fetch,
    browser_search,
    search_hotels,
    run_command,
]
