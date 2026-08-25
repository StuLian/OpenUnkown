"""轻量 BM25 关键词打分。

向量检索擅长语义相似，但对「泳池」「机场」「健身房」这类精确设施词，
关键词命中往往更准。BM25 基于词频/逆文档频率给文档打分，与向量检索互补，
用于混合检索中的词法一路。

这里不引入额外依赖，用 numpy 直接实现 Okapi BM25。
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class BM25:
    """Okapi BM25 检索器，corpus 为文档文本列表。"""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.tokenized: list[list[str]] = [self._tokenize(t) for t in corpus]
        self.n_docs = len(corpus)
        self.doc_len = [len(d) for d in self.tokenized]
        self.avgdl = float(np.mean(self.doc_len)) if self.doc_len else 1.0

        # 每个词出现在多少篇文档里（文档频率）
        self.doc_freq: Counter[str] = Counter()
        for doc in self.tokenized:
            for term in set(doc):
                self.doc_freq[term] += 1

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text.lower())

    def _idf(self, term: str) -> float:
        df = self.doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score_all(self, query: str) -> np.ndarray:
        """返回 query 对每篇文档的 BM25 分数（长度 = 文档数）。"""
        qterms = self._tokenize(query)
        scores = np.zeros(self.n_docs, dtype=np.float32)
        for term in qterms:
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for i, doc in enumerate(self.tokenized):
                tf = doc.count(term)
                if tf == 0:
                    continue
                norm = tf + self.k1 * (
                    1.0 - self.b + self.b * (self.doc_len[i] / self.avgdl)
                )
                scores[i] += idf * (tf * (self.k1 + 1.0)) / norm
        return scores
