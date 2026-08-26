"""西雅图酒店检索工具。

基于 FAISS + DashScope 向量化，把用户对酒店的需求（位置、设施、风格等）
检索为最相关的酒店列表，供模型引用作答，避免凭空编造酒店信息。
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from backend.rag import search_hotels as _rag_search_hotels

# 单条结果返回给模型时的描述截断长度，避免多结果叠加过长
_DESC_LIMIT = 700


def _format_result(results: list[dict]) -> str:
    """把检索结果格式化为模型易读的文本。"""
    if not results:
        return "未检索到相关酒店。"

    lines = [f"检索到 {len(results)} 家相关酒店（按相关度降序）："]
    for i, r in enumerate(results, 1):
        desc = r["desc"]
        if len(desc) > _DESC_LIMIT:
            desc = desc[:_DESC_LIMIT] + "…"
        lines.append(
            f"\n[{i}] {r['name']}\n"
            f"    地址: {r['address']}\n"
            f"    相关度: {r['score']:.3f}\n"
            f"    简介: {desc}"
        )
    return "\n".join(lines)


@tool
def search_hotels(query: str, top_k: int = 5, config: RunnableConfig = None) -> str:
    """在西雅图酒店数据中检索相关酒店。

    当用户询问西雅图的酒店推荐、找酒店、比价、酒店设施（泳池/健身房/餐厅/会议室等）、
    位置（市中心/机场/海滨等）、交通便利度等时，必须调用本工具获取真实数据，
    不要凭记忆编造酒店名称或设施。

    Args:
        query: 检索查询，用英文描述需求最准确，例如 "hotel with indoor pool near downtown Seattle"。
        top_k: 返回的酒店数量，默认 5，取值范围 1-10。
    """
    top_k = max(1, min(int(top_k), 10))
    cfg = (config or {}).get("configurable") or {}
    api_key = cfg.get("api_key") or ""
    results = _rag_search_hotels(query, top_k=top_k, api_key=api_key)
    return _format_result(results)
