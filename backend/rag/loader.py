"""西雅图酒店 CSV 的加载与清洗。

原始文件 csv/Seattle_Hotels.csv 是 cp1252 编码，desc 字段里带有换行、
不换行空格(\\xa0)、软连字符(\\xad)，以及部分历史转换遗留的乱码问号(``?``)——
这些问号实际是撇号、注册商标符 ®、度数 ° 等字符在早期转码时丢失造成的。

本模块只做轻量清洗：转码、折叠空白、修正常见英文缩写，不做过度改写，
保证每条酒店记录在向量化与检索时保持原意。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import TypedDict

from backend.rag.location import extract_locations

# 项目根目录下的数据文件路径
CSV_PATH = Path(__file__).resolve().parent.parent.parent / "csv" / "Seattle_Hotels.csv"

# 常见英文缩写：? 被替换成了丢失的撇号
_CONTRACTION_FIXES = [
    (r"\?re\b", "'re"),
    (r"\?s\b", "'s"),
    (r"\?ll\b", "'ll"),
    (r"\?ve\b", "'ve"),
    (r"\?t\b", "'t"),
    (r"\?d\b", "'d"),
    (r"\?m\b", "'m"),
]

_WHITESPACE_RE = re.compile(r"\s+")


class HotelDoc(TypedDict):
    """单条酒店检索文档。"""

    name: str
    address: str
    desc: str
    text: str  # 拼接后的可嵌入文本
    location: list[str]  # 从 name/address 提取的规范位置标签


def clean_text(text: str) -> str:
    """清洗一段文本：折叠空白、修正缩写问号乱码。"""
    text = text.replace("\xa0", " ").replace("\xad", "")
    for pattern, repl in _CONTRACTION_FIXES:
        text = re.sub(pattern, repl, text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def load_hotels() -> list[HotelDoc]:
    """读取并清洗 CSV，返回酒店文档列表。

    每行生成一条文档，text 字段由 name/address/desc 拼接而成，作为向量化输入；
    name/address 作为元数据保留，供检索结果引用与过滤。
    """
    docs: list[HotelDoc] = []
    with open(CSV_PATH, newline="", encoding="cp1252") as f:
        for row in csv.DictReader(f):
            name = clean_text(row.get("name", ""))
            address = clean_text(row.get("address", ""))
            desc = clean_text(row.get("desc", ""))
            if not name and not desc:
                continue
            text = f"{name}. {address}. {desc}"
            docs.append(
                HotelDoc(
                    name=name,
                    address=address,
                    desc=desc,
                    text=text,
                    location=extract_locations(name, address),
                )
            )
    return docs
