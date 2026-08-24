"""极简测试 MCP Server：提供计算两个数字加法的简单工具。"""
import asyncio
from mcp.server import FastMCP

mcp = FastMCP("calculator")


@mcp.tool()
def add_numbers(a: float, b: float) -> float:
    """计算两个数字相加的精确结果。"""
    return a + b


if __name__ == "__main__":
    mcp.run()
