"""工具意图路由：关键词快速通道 + embedding 语义召回兜底。

背景（见 graph.py）：闲聊/不相关时不绑定工具，省掉全部工具 schema 的固定 token
底噪（高德一家就 12 个）。原先只有关键词硬匹配，子串命中才算数，改写一多就漏
（例：「明天上海冷吗」命中不了「冷不冷」）。

本模块把「关键词」降级为**高精度快速通道**（命中即绑定，零额外延迟/成本），
未命中时用 text-embedding-v3 把查询向量化，与各工具组的**语义锚点**（代表性问法
清单，是数据而非规则，新增覆盖只需补一句样例）做余弦相似度，超过阈值视为命中。
这样既补齐关键词的漏召回，又保持「闲聊不绑工具」的 token 收益。

锚点向量按需懒加载并缓存：embedding 模型与平台全局一致，锚点向量与具体用户无关，
任一用户首次触发后即可复用（仅查询向量每次按当前用户 ApiKey 现算）。
"""
from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np

from backend.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 关键词快速通道：命中即绑定，不触发 embedding 调用。
# 只承担「高置信、低歧义」的显式表达；其余改写交给下方语义锚点兜底。
# ---------------------------------------------------------------------------
_WEATHER_KWS = (
    "天气", "气温", "温度", "下雨", "下雪", "降雨", "降温", "气候",
    "冷不冷", "热不热", "多少度", "weather",
)
_MAP_KWS = (
    "地图", "路线", "路况", "导航", "规划", "怎么走", "怎么去", "附近", "周边",
    "位置", "坐标", "经纬", "距离", "多远", "骑行", "步行", "驾车", "开车",
    "公交", "地铁", "打车", "高德", "地址", "在哪", "poi",
)
_FEISHU_KWS = (
    "飞书", "lark", "文档", "docx", "wiki", "多维表格", "电子表格", "表格",
    "sheet", "日历", "日程", "会议", "待办", "任务", "邮件", "邮箱",
    "云盘", "云空间", "知识库", "妙记", "审批", "通讯录", "考勤",
    "幻灯片", "画板", "okr", "feishu.cn", "larksuite",
)
_BROWSE_KWS = (
    "网页", "网站", "网址", "链接", "打开网页", "浏览", "抓取", "爬取", "访问网页",
    "上网", "在线", "互联网", "搜索", "检索", "搜一下", "搜索引擎", "热搜",
    "新闻", "资讯", "最新消息", "web", "url", "http", "browse", "search", "fetch",
    # 股票/财经类：无专门行情工具，统一路由到 browser_search 联网检索
    "股票", "股价", "行情", "大盘", "上证", "深证", "涨跌", "涨幅", "跌幅",
    "市值", "财报", "美股", "港股", "a股", "收盘", "开盘", "证券",
)
_HOTEL_KWS = (
    "酒店", "hotel", "宾馆", "旅馆", "住宿", "民宿", "订房", "订酒店", "入住",
    "房型", "西雅图", "seattle", "客房", "泳池", "健身房", "会议室", "含早",
    "机场酒店", "海景", "套房", "前台", "退房",
)

_KEYWORD_MAP = {
    "weather": _WEATHER_KWS,
    "map": _MAP_KWS,
    "feishu": _FEISHU_KWS,
    "browse": _BROWSE_KWS,
    "hotel": _HOTEL_KWS,
}

# ---------------------------------------------------------------------------
# 语义锚点：每个意图一组代表性问法（覆盖常见改写，而非罗列关键词）。
# 这是「数据」而非「规则」：漏召回时补一句样例，而不是再想一个关键词。
# ---------------------------------------------------------------------------
_ANCHORS: dict[str, tuple[str, ...]] = {
    "weather": (
        "查一下天气",
        "今天冷不冷",
        "明天会下雨吗",
        "气温多少度",
        "出门要不要带伞",
        "北京现在热不热",
        "上海明天冷吗",
        "周末天气怎么样",
        "会下雪吗",
    ),
    "map": (
        "帮我查一下路线",
        "从这里怎么过去",
        "附近有什么好吃的",
        "导航到火车站",
        "打车去机场要多久",
        "坐地铁怎么走",
        "步行过去多远",
        "周边有哪些景点",
    ),
    "feishu": (
        "帮我查飞书文档",
        "今天有什么会议",
        "我的待办任务有哪些",
        "这条审批到哪一步了",
        "帮我发一封邮件",
        "查一下我的考勤",
        "云盘里找一下文件",
        "知识库里搜一下",
    ),
    "browse": (
        "上网搜一下最新消息",
        "帮我抓取这个网页的内容",
        "最近有什么新闻",
        "这只股票现在什么行情",
        "帮我查最新资讯",
    ),
    "hotel": (
        "帮我订一家酒店",
        "西雅图有什么酒店推荐",
        "找一家带泳池的酒店",
        "机场附近的酒店",
        "民宿预订",
        "住宿推荐",
    ),
}

# 语义召回判定（用真实 text-embedding-v3 数据校准，勿拍脑袋调）：
# 短中文的基线余弦相似度约 0.5，因此不能只设一个绝对阈值——那会连「给我讲个笑话」
# 都把五个工具组全绑上。实测：真意图锚点相似度 >= 0.86 且领先第二名 >= 0.24；
# 闲聊 top1 <= 0.64、领先 <= 0.10；裸城市名（北京/上海）top1 <= 0.66、领先 <= 0.09。
# 故要求「绝对分数够高 且 明显领先第二名」才算命中；裸城市名这类弱信号交给多轮继承兜底。
_SIM_FLOOR = 0.75   # 绝对下限：真意图 >= 0.86，闲聊/裸城市 <= 0.66
_SIM_MARGIN = 0.15  # 领先第二名的边距：真意图 >= 0.24，闲聊/裸城市 <= 0.10

# 锚点向量缓存：group -> (n, dim) 已归一化矩阵。embedding 模型跨用户一致，只算一次。
_anchor_vecs: dict[str, np.ndarray] | None = None
_anchor_lock = threading.Lock()


def _hit(text: str, kws: tuple[str, ...]) -> bool:
    """判断文本是否命中关键词组（快速通道）。"""
    return any(k in text for k in kws)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """按行 L2 归一化，零向量保持为零。"""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _ensure_anchor_vecs(api_key: str) -> dict[str, np.ndarray]:
    """懒加载各意图锚点向量（首次调用时用当前用户 ApiKey 计算并缓存）。"""
    global _anchor_vecs
    if _anchor_vecs is not None:
        return _anchor_vecs
    with _anchor_lock:
        if _anchor_vecs is not None:
            return _anchor_vecs
        groups = list(_ANCHORS.keys())
        flat: list[str] = []
        sizes: list[int] = []
        for g in groups:
            anchors = _ANCHORS[g]
            sizes.append(len(anchors))
            flat.extend(anchors)
        vectors = embed_texts(flat, text_type="query", api_key=api_key)
        matrix = _normalize(np.array(vectors, dtype="float32"))
        result: dict[str, np.ndarray] = {}
        idx = 0
        for g, size in zip(groups, sizes):
            result[g] = matrix[idx : idx + size]
            idx += size
        _anchor_vecs = result
        logger.info("[意图路由] 锚点向量已构建: %d 组 %d 条", len(groups), len(flat))
    return _anchor_vecs


async def _semantic_hits(text: str, api_key: str) -> dict[str, bool]:
    """语义召回：只认「绝对分数高且明显领先」的第一名，其余视为闲聊/背景。

    返回 {group: bool}；最多只有一个 group 为 True（多意图优先走关键词快速通道）。
    """
    anchors = await asyncio.to_thread(_ensure_anchor_vecs, api_key)
    query_vec = np.array(
        (await asyncio.to_thread(embed_texts, [text], text_type="query", api_key=api_key))[0],
        dtype="float32",
    )
    query_vec = _normalize(query_vec.reshape(1, -1))[0]

    sims: dict[str, float] = {
        group: float((query_vec @ anchor_matrix.T).max())
        for group, anchor_matrix in anchors.items()
    }
    ranked = sorted(sims.items(), key=lambda kv: -kv[1])
    hits = {group: False for group in sims}
    if ranked:
        top_group, top_sim = ranked[0]
        second_sim = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_sim >= _SIM_FLOOR and (top_sim - second_sim) >= _SIM_MARGIN:
            hits[top_group] = True
    logger.info(
        "[意图路由] 语义召回: %r -> %s",
        text,
        {k: round(v, 3) for k, v in sims.items()},
    )
    return hits


async def _route_single(text: str, api_key: str) -> dict[str, bool]:
    """对单条文本路由：关键词快速通道，未命中再语义召回兜底。"""
    low = text.lower().strip()
    want = {group: _hit(low, kws) for group, kws in _KEYWORD_MAP.items()}
    if any(want.values()) or not low:
        return want
    try:
        semantic = await _semantic_hits(low, api_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("[意图路由] 语义召回失败，回退关键词结果: %s", e)
        return want
    for group, hit in semantic.items():
        if hit:
            want[group] = True
    return want


# 短跟随消息(如只补一个城市名「北京」/日期「明天」/地点「虹桥机场」)继承上一轮意图的
# 最大字符数。超过此长度视为自含意图的新问题，不继承，避免把陈旧意图一直带下去。
# 城市/日期/地点类补答基本都在 5 字内；即便偶尔误继承，也只是多绑一个工具 schema
# （模型仍会看工具描述决定是否调用），不会给出错误答案。
_FOLLOWUP_MAX_CHARS = 5


async def route_intents(text: str, api_key: str, prev_user_text: str = "") -> dict[str, bool]:
    """返回各意图是否命中：weather/map/feishu/browse/hotel。

    关键词命中走快速通道（同步、零网络）；全部未命中且文本非空时，
    才向量化查询做语义召回兜底。embedding 失败不回退到全绑定，
    而是保持关键词结果，避免把闲聊也带上全部工具 schema（下轮会重试）。

    多轮澄清：当最新消息是短片段且自身表达不出意图（如用户只回「北京」补城市名），
    会继承上一轮用户的意图，保证上一轮未完成的工具任务（如查天气）能继续，
    而不是因为一个简单的城市名就丢掉天气意图。
    """
    low = text.lower().strip()
    want = await _route_single(text, api_key)
    if any(want.values()) or not low:
        return want

    if prev_user_text and len(low) <= _FOLLOWUP_MAX_CHARS:
        prev_want = await _route_single(prev_user_text, api_key)
        if any(prev_want.values()):
            return prev_want
    return want
