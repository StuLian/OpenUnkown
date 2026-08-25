"""DashScope 文本向量化封装。

使用 text-embedding-v3（1024 维），支持批量输入，区分 document/query 两种
text_type：文档入库用 document，查询时用 query，二者共享同一向量空间。
"""
from __future__ import annotations

from dashscope import TextEmbedding

from backend.config import get_api_key

EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024
# text-embedding-v3 单次批量上限（实测不超过 10），超过则分批
BATCH_SIZE = 10


def embed_texts(texts: list[str], text_type: str = "document") -> list[list[float]]:
    """把一批文本向量化为 1024 维浮点向量，保持输入顺序。

    Args:
        texts: 待向量化的文本列表。
        text_type: "document"（入库）或 "query"（检索）。
    """
    api_key = get_api_key()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = TextEmbedding.call(
            model=EMBED_MODEL,
            input=batch,
            dimension=EMBED_DIM,
            text_type=text_type,
            api_key=api_key,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"向量化失败: code={getattr(resp, 'code', '?')} "
                f"message={getattr(resp, 'message', str(resp))}"
            )
        # 服务端返回顺序与输入一致，但仍按 text_index 排序保证稳定
        embeddings = sorted(
            resp.output["embeddings"], key=lambda e: e.get("text_index", 0)
        )
        vectors.extend(e["embedding"] for e in embeddings)
    return vectors
