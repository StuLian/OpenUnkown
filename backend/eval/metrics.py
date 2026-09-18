"""检索评测指标：recall@k / MRR / nDCG@k（二元相关性）。

约定：relevant 为「黄金标准」相关文档 id/名称列表，retrieved 为检索返回的
有序结果 id/名称列表。匹配按集合成员（名称精确相等），不按排序分数。
"""
from __future__ import annotations

import math


def recall_at_k(relevant: list[str], retrieved: list[str], k: int) -> float:
    """返回 top-k 中命中 relevant 的比例：|relevant ∩ retrieved[:k]| / |relevant|。"""
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in rel)
    return hits / len(rel)


def mrr(relevant: list[str], retrieved: list[str]) -> float:
    """Mean Reciprocal Rank 单查询值：第一个命中的倒数排名，未命中为 0。"""
    rel = set(relevant)
    for i, r in enumerate(retrieved, 1):
        if r in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: list[str], retrieved: list[str], k: int) -> float:
    """二元相关性的 nDCG@k：relevant 记 1，其余记 0。"""
    rel = set(relevant)
    k = min(k, len(retrieved))
    if k <= 0:
        return 0.0
    dcg = sum(
        1.0 / math.log2(i + 2) for i in range(k) if retrieved[i] in rel
    )
    ideal_n = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_n))
    return dcg / idcg if idcg else 0.0


def mean(values: list[float]) -> float:
    """平均值（空列表返回 0）。"""
    return sum(values) / len(values) if values else 0.0
