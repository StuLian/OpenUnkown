"""DashScope 重排（Rerank）封装。

混合检索先召回一批候选，再用重排模型按「查询—文档」逐对相关度重新排序，
能显著提升最终 top-k 的命中精度。使用 gte-rerank-v2。
"""
from __future__ import annotations

from dashscope import TextReRank

from backend.config import get_api_key

RERANK_MODEL = "gte-rerank-v2"


def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """按相关度重排文档。

    Args:
        query: 查询文本。
        documents: 候选文档列表（保持原顺序）。
        top_n: 返回前几名；None 表示返回全部。

    Returns:
        [(原始下标, 相关度分)] 按相关度降序排列。
    """
    if not documents:
        return []
    resp = TextReRank.call(
        model=RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=min(top_n or len(documents), len(documents)),
        api_key=get_api_key(),
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"重排失败: code={getattr(resp, 'code', '?')} "
            f"message={getattr(resp, 'message', str(resp))}"
        )
    results = sorted(
        resp.output["results"], key=lambda r: r.relevance_score, reverse=True
    )
    return [(int(r.index), float(r.relevance_score)) for r in results]
