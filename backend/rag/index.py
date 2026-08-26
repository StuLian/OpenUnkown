"""FAISS 向量索引的构建、持久化与混合检索。

检索链路：向量(余弦) + BM25(词法) → RRF 融合 → gte-rerank-v2 重排 → top-k。
索引与文档元数据持久化到 data/hotels/ 目录，首次构建后即可离线加载，
无需每次重启都重新调用 embedding 接口（BM25 在内存中按文档即时重建，无 API 开销）。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import faiss
import numpy as np

from backend.rag.bm25 import BM25
from backend.rag.embeddings import EMBED_DIM, embed_texts
from backend.rag.loader import HotelDoc, load_hotels
from backend.rag.location import detect_query_locations
from backend.rag.rerank import rerank

logger = logging.getLogger(__name__)

# 持久化目录: 项目根 data/hotels/
INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "hotels"
DOCS_PATH = INDEX_DIR / "docs.json"
INDEX_PATH = INDEX_DIR / "hotels.index"

# RRF 融合常数（业界常用 60）
RRF_K = 60
# 混合检索送入重排的候选数量
RERANK_CANDIDATES = 20

# 索引与文档缓存的构建锁，避免并发首次构建重复执行
_build_lock = threading.Lock()


def _refilter_ranks(ranks: dict[int, int], allowed: set[int]) -> dict[int, int]:
    """按 allowed 集合过滤排名，并对保留项重新编号为 1..N。

    RRF 对排名绝对值敏感，过滤掉中间名次后必须重排，否则保留项会因名次
    出现空洞而被不公平地压低分数。
    """
    kept = sorted(
        ((doc_id, rank) for doc_id, rank in ranks.items() if doc_id in allowed),
        key=lambda x: x[1],
    )
    return {doc_id: new_rank for new_rank, (doc_id, _) in enumerate(kept, 1)}


def rrf_fuse(rank_maps: list[dict[int, int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：把多路「doc_id -> 排名」融合成统一相关度。

    RRF 不需要对分数归一化（向量余弦与 BM25 量纲不同），只按排名取倒数求和，
    对「某一路排得靠前」的文档天然友好，稳健且实现简单。
    """
    fused: dict[int, float] = {}
    for ranks in rank_maps:
        for doc_id, rank in ranks.items():
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda x: -x[1])


class HotelIndex:
    """封装 FAISS 索引、BM25 检索器与酒店文档元数据。"""

    def __init__(self, docs: list[HotelDoc], index: faiss.IndexFlatIP):
        self.docs = docs
        self.index = index
        # BM25 从文档文本即时重建，无需持久化、无 API 开销
        self.bm25 = BM25([d["text"] for d in docs])

    def _vector_search(self, query: str, api_key: str) -> tuple[dict[int, int], dict[int, float]]:
        """向量全文检索：返回 (doc_id->排名, doc_id->余弦分)。"""
        query_vec = np.array(embed_texts([query], text_type="query", api_key=api_key)[0], dtype="float32")
        query_vec = query_vec.reshape(1, -1)
        faiss.normalize_L2(query_vec)
        scores, ids = self.index.search(query_vec, self.index.ntotal)
        ranks: dict[int, int] = {}
        cos_map: dict[int, float] = {}
        for rank, (score, idx) in enumerate(zip(scores[0], ids[0]), 1):
            idx = int(idx)
            if idx >= 0:
                ranks[idx] = rank
                cos_map[idx] = float(score)
        return ranks, cos_map

    def _bm25_search(self, query: str) -> dict[int, int]:
        """BM25 检索：返回 doc_id -> 排名（仅包含得分 > 0 的文档）。"""
        scores = self.bm25.score_all(query)
        order = np.argsort(-scores)
        ranks: dict[int, int] = {}
        for rank, idx in enumerate(order, 1):
            idx = int(idx)
            if scores[idx] > 0:
                ranks[idx] = rank
        return ranks

    def search(self, query: str, top_k: int = 5, api_key: str = "") -> list[dict]:
        """混合检索与 query 最相关的酒店。

        向量 + BM25 经 RRF 融合召回候选，再用 rerank 重排取 top_k；
        rerank 失败时自动回退到混合排序，保证检索永不因重排异常而失败。

        Returns:
            按相关度降序的结果列表，每项含 name/address/desc/score。
        """
        if not self.docs:
            return []

        vec_ranks, cos_map = self._vector_search(query, api_key)
        bm25_ranks = self._bm25_search(query)

        # 位置结构化过滤：查询带位置意图时，只保留对应区域的酒店
        loc_tags = detect_query_locations(query)
        if loc_tags:
            allowed = {
                i
                for i, d in enumerate(self.docs)
                if set(d.get("location", [])) & set(loc_tags)
            }
            if allowed:
                vec_ranks = _refilter_ranks(vec_ranks, allowed)
                bm25_ranks = _refilter_ranks(bm25_ranks, allowed)
                logger.info("位置过滤: %s -> %d 家候选", loc_tags, len(allowed))
            # allowed 为空说明提取不到匹配酒店，回退到不过滤，保证有结果

        fused = rrf_fuse([vec_ranks, bm25_ranks])
        if not fused:
            return []

        # 取 RRF 前若干候选送入重排
        cand_ids = [doc_id for doc_id, _ in fused[:RERANK_CANDIDATES]]
        final: list[tuple[int, float]] | None = None
        try:
            cand_texts = [self.docs[i]["text"] for i in cand_ids]
            reranked = rerank(query, cand_texts, top_n=min(top_k, len(cand_ids)), api_key=api_key)
            final = [(cand_ids[idx], score) for idx, score in reranked]
        except Exception as e:  # noqa: BLE001
            logger.warning("rerank 失败，回退到混合排序: %s", e)
            final = None

        if final is None:
            # 回退：直接用 RRF 顺序，分数用余弦相似度便于展示
            final = [(doc_id, cos_map.get(doc_id, 0.0)) for doc_id, _ in fused]

        results: list[dict] = []
        for doc_id, score in final[:top_k]:
            doc = self.docs[doc_id]
            results.append(
                {
                    "name": doc["name"],
                    "address": doc["address"],
                    "desc": doc["desc"],
                    "score": float(score),
                }
            )
        return results


def _persist(docs: list[HotelDoc], index: faiss.IndexFlatIP) -> None:
    """把文档元数据与 FAISS 索引写入磁盘。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    faiss.write_index(index, str(INDEX_PATH))


def _load_from_disk() -> HotelIndex | None:
    """磁盘上已有索引时直接加载，避免重复调用 embedding。"""
    if not (DOCS_PATH.exists() and INDEX_PATH.exists()):
        return None
    try:
        docs = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
        index = faiss.read_index(str(INDEX_PATH))
        return HotelIndex(docs=docs, index=index)
    except Exception as e:
        logger.warning("加载酒店索引失败，将重新构建: %s", e)
        return None


def _build(api_key: str) -> HotelIndex:
    """加载 CSV → 向量化 → 构建 FAISS 索引并持久化。"""
    docs = load_hotels()
    texts = [d["text"] for d in docs]
    vectors = embed_texts(texts, text_type="document", api_key=api_key)
    matrix = np.array(vectors, dtype="float32")
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(matrix)
    hotel_index = HotelIndex(docs=docs, index=index)
    _persist(docs, index)
    logger.info("酒店索引构建完成：%d 条，维度 %d", len(docs), EMBED_DIM)
    return hotel_index


# 模块级单例缓存
_hotel_index: HotelIndex | None = None


def get_hotel_index(force_rebuild: bool = False, api_key: str = "") -> HotelIndex:
    """获取酒店索引单例；磁盘有索引时直接加载，否则首次调用时构建。

    force_rebuild=True 时跳过磁盘缓存，强制重新清洗、向量化并覆盖持久化文件。
    api_key 仅在需要构建索引（首次或强制重建）时使用。
    """
    global _hotel_index
    if force_rebuild:
        _hotel_index = None
    if _hotel_index is not None:
        return _hotel_index
    with _build_lock:
        if _hotel_index is None:
            _hotel_index = _build(api_key) if force_rebuild else (_load_from_disk() or _build(api_key))
    return _hotel_index


def search_hotels(query: str, top_k: int = 5, api_key: str = "") -> list[dict]:
    """混合检索相关酒店（对 get_hotel_index 的便捷封装）。"""
    return get_hotel_index(api_key=api_key).search(query, top_k=top_k, api_key=api_key)
