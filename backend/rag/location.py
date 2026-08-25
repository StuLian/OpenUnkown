"""酒店位置标签的提取与查询位置意图识别。

酒店数据没有结构化坐标，位置信息散落在 name/address 里。
本模块把「酒店属于哪个区域」和「用户在问哪个区域」都归一成同一套规范标签，
检索时据此做结构化过滤，解决「downtown 查询返回郊区酒店」这类问题。

设计要点：
- 酒店名里的位置词是最干净的信号（如 "Crowne Plaza ... Downtown"）。
- 街道名可能误导（"University St" 是市中心街道，不是大学区），所以
  大学区只在出现 "university district" / "university of washington" 时才算。
- 非西雅图市区的郊区靠城市名识别（Tukwila / Renton / SeaTac 等）。
"""
from __future__ import annotations

import re

# 规范标签 ← 酒店 name+address 中的关键词（小写）
_NAME_RULES: list[tuple[str, list[str]]] = [
    ("downtown", [
        "downtown", "city center", "city-center", "pioneer square",
        "pike place", "pike's place", "convention center",
    ]),
    ("airport", [
        "airport", "seatac", "sea-tac", "sea tac", "international blvd",
    ]),
    ("south lake union", ["south lake union", "lake union"]),
    ("queen anne", ["queen anne", "space needle"]),
    ("waterfront", ["waterfront", "water front"]),
    ("university district", ["university district", "university of washington"]),
    ("capitol hill", ["capitol hill"]),
    ("belltown", ["belltown"]),
    ("northgate", ["northgate"]),
    ("ballard", ["ballard"]),
    ("west seattle", ["west seattle"]),
    ("south", ["tukwila", "southcenter", "south center", "renton", "des moines"]),
    ("eastside", ["bellevue", "redmond"]),
]

# 非西雅图市区的城市名 → 规范标签
_CITY_TAGS: dict[str, str] = {
    "seatac": "airport",
    "tukwila": "south",
    "des moines": "south",
    "renton": "south",
    "bellevue": "eastside",
    "redmond": "eastside",
    "shoreline": "north",
}

# 邮编 → 规范标签（邮编是识别市中心最可靠的信号：98101/98104/98121）
_ZIP_TAGS: dict[str, str] = {
    "98101": "downtown",
    "98104": "downtown",
    "98121": "downtown",
    "98188": "airport",
    "98198": "airport",
    "98105": "university district",
    "98102": "capitol hill",
    "98122": "capitol hill",
    "98168": "south",
    "98056": "south",
    "98119": "queen anne",
    "98004": "eastside",
    "98052": "eastside",
    "98107": "ballard",
    "98136": "west seattle",
    "98126": "west seattle",
    "98133": "northgate",
}

# 查询关键词 → 规范标签（中英文都支持）
_QUERY_RULES: list[tuple[str, list[str]]] = [
    ("downtown", [
        "downtown", "city center", "pioneer square", "pike place",
        "convention center", "市中心", "市区", "商业区", "派克市场", "先驱广场",
    ]),
    ("airport", ["airport", "seatac", "sea-tac", "sea tac", "机场"]),
    ("south lake union", ["south lake union", "lake union", "slu", "联合湖", "南联合湖"]),
    ("queen anne", ["queen anne", "space needle", "太空针", "安妮女王", "皇后安妮"]),
    ("waterfront", ["waterfront", "water front", "海滨", "海边", "码头", "港口"]),
    ("university district", [
        "university district", "university of washington", "大学", "华盛顿大学",
    ]),
    ("capitol hill", ["capitol hill", "国会山"]),
    ("belltown", ["belltown", "贝尔镇"]),
    ("northgate", ["northgate", "北门"]),
    ("ballard", ["ballard", "巴拉德"]),
    ("west seattle", ["west seattle", "西西雅图", "西雅图西"]),
    ("south", ["tukwila", "southcenter", "renton", "des moines", "南边", "南郊"]),
    ("eastside", ["bellevue", "redmond", "东区", "贝尔维尤"]),
]


def _extract_city(address: str) -> str:
    """从地址里识别已知城市名（小写），识别不到返回空串。"""
    a = address.lower()
    for city in _CITY_TAGS:
        if city in a:
            return city
    return ""


def _extract_zip(address: str) -> str:
    """从地址提取真实邮编：取最后一个 5 位数字（地址格式不统一，最靠后的才是邮编）。"""
    nums = re.findall(r"\b\d{5}(?:-\d{4})?\b", address)
    if not nums:
        return ""
    return nums[-1].split("-")[0]


def extract_locations(name: str, address: str) -> list[str]:
    """从酒店 name/address 提取规范位置标签（可能多个，按字母序）。"""
    text = f"{name} {address}".lower()
    tags: set[str] = set()

    zip_code = _extract_zip(address)
    if zip_code in _ZIP_TAGS:
        tags.add(_ZIP_TAGS[zip_code])

    city = _extract_city(address)
    if city in _CITY_TAGS:
        tags.add(_CITY_TAGS[city])

    for tag, kws in _NAME_RULES:
        if any(k in text for k in kws):
            tags.add(tag)
    return sorted(tags)


def detect_query_locations(query: str) -> list[str]:
    """识别查询中的位置意图，返回规范标签列表（可能多个）。"""
    q = query.lower()
    return [tag for tag, kws in _QUERY_RULES if any(k in q for k in kws)]
