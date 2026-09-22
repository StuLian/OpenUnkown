"""read_skill 工具：让模型按需读取本地 skill 的说明书正文与参考文件（只读）。"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.agent.skills.loader import load_skill_doc, load_skill_ref


@tool
async def read_skill(skill_name: str, ref_path: str = "") -> str:
    """读取本地 skill 的说明书。当用户任务匹配某个 skill 时，先调用本工具拿到正文，
    再严格按其工作流执行；正文里引用的参考文件用 ref_path 按需再读。

    Args:
        skill_name: skill 名（「本地 Skill 目录」里列出的名字，如 'ai-daily-report'、'lark-doc'）。
        ref_path: 可选，skill 目录内的参考文件相对路径（如 'references/content-schema.md'）。
                  留空则返回该 skill 的正文说明。
    """
    if ref_path:
        return load_skill_ref(skill_name, ref_path)
    return load_skill_doc(skill_name)
