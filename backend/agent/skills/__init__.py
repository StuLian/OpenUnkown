"""技能包：扫描本地 skill 目录、生成目录、按需读取说明书。

对外暴露：
- get_skill_index / get_skill_directory：扫描与目录生成（graph.py 注入 prompt 用）；
- read_skill：LangChain 工具（模型按需拉取 skill 正文与 references）。
"""
from backend.agent.skills.registry import get_skill_directory, get_skill_index
from backend.agent.skills.reader import read_skill

__all__ = ["get_skill_index", "get_skill_directory", "read_skill"]
