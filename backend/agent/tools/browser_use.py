"""网页浏览工具：browser_fetch 抓取网页正文、browser_search 网络搜索。

沿用 weather.py 的轻量 httpx 实现，不引入无头浏览器、额外进程或 API Key。
正文提取与搜索结果解析只用标准库 html.parser，无新增依赖。
"""
from __future__ import annotations

import base64
import html as _html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from langchain_core.tools import tool

# 伪装成普通浏览器，降低被站点反爬/重定向拦截的概率
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_TIMEOUT = 20.0
_MAX_TEXT = 4000  # 返回给模型的正文上限(字符)，避免长页面撑爆上下文


class _TextExtractor(HTMLParser):
    """把 HTML 转成接近正文的纯文本：记录 title/description，块级标签换行。

    跳过 script/style 等不可见内容，行内标签仅保留文本。
    """

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}
    _BLOCK_TAGS = {
        "p", "div", "li", "ul", "ol", "tr", "br",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "blockquote", "pre", "table",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._parts: list[str] = []
        self._buf: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip += 1
            return
        attrs = dict(attrs)
        if tag == "meta" and (attrs.get("name") or "").lower() == "description":
            desc = (attrs.get("content") or "").strip()
            if desc and not self.description:
                self.description = desc
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        text = data.strip()
        if text:
            self._buf.append(text)

    def _flush(self) -> None:
        if self._buf:
            self._parts.append(" ".join(self._buf))
            self._buf = []

    def get_text(self) -> str:
        self._flush()
        return "\n".join(self._parts)


def _normalize_url(url: str) -> str:
    """补全缺协议的主机名，方便用户直接丢 'example.com'。"""
    url = url.strip()
    if not url:
        return url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


@tool
def browser_fetch(url: str) -> str:
    """抓取指定网页并返回可读的纯文本正文。用户给出网址/链接、要求查看或阅读某个网页内容时必须调用本工具。

    Args:
        url: 目标网页地址，需带 http:// 或 https:// 协议，例如 'https://example.com/article'。
    """
    url = _normalize_url(url)
    if not url:
        return "Error: url 不能为空。"

    try:
        with httpx.Client(
            headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:  # noqa: BLE001
        return f"Error: 抓取失败: {e}"

    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:  # noqa: BLE001
        pass

    title = " ".join(extractor.title.split())
    desc = " ".join(extractor.description.split())
    body = extractor.get_text().strip()

    parts: list[str] = []
    if title:
        parts.append(f"标题: {title}")
    if desc:
        parts.append(f"摘要: {desc}")
    parts.append(body if body else "(未提取到正文，可能是 JS 动态渲染或反爬页面)")

    text = "\n\n".join(parts)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + "\n...(已截断，原文更长)"
    return text


def _is_ad_href(href: str) -> bool:
    """判断 DuckDuckGo 结果链接是否为广告（y.js 重定向 / bing aclick）。"""
    if not href:
        return False
    lower = href.lower()
    return any(m in lower for m in ("duckduckgo.com/y.js", "ad_domain", "ad_provider", "aclick"))


def _extract_ddg_url(href: str) -> str:
    """把 DuckDuckGo 的重定向链接还原成真实目标 URL。"""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc:
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return href


class _DDGResultParser(HTMLParser):
    """解析 DuckDuckGo HTML 搜索结果：标题链接 + 摘要片段，跳过广告位。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._current: dict | None = None
        self._in_link = False
        self._in_snippet = False
        self._in_ad = False
        self._link_buf: list[str] = []
        self._snippet_buf: list[str] = []

    def _append_pending(self) -> None:
        if self._current and (self._current["url"] or self._current["title"]):
            self.results.append(self._current)
        self._current = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs = dict(attrs)
        cls = (attrs.get("class") or "").lower()
        if tag == "a" and "result__a" in cls:
            self._append_pending()
            self._in_ad = _is_ad_href(attrs.get("href", ""))
            self._in_link = True
            self._link_buf = []
            self._current = None if self._in_ad else {
                "url": _extract_ddg_url(attrs.get("href", "")),
                "title": "",
                "snippet": "",
            }
        elif tag == "a" and "result__snippet" in cls:
            self._in_snippet = True
            self._snippet_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
            if self._current:
                self._current["title"] = " ".join("".join(self._link_buf).split())
            self._in_ad = False
        elif tag == "a" and self._in_snippet:
            self._in_snippet = False
            if self._current:
                self._current["snippet"] = " ".join("".join(self._snippet_buf).split())
            self._append_pending()

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_buf.append(data)
        elif self._in_snippet and self._current:
            self._snippet_buf.append(data)


def _ddg_search(query: str, limit: int) -> list[dict]:
    """调用 DuckDuckGo HTML 搜索，返回 title/url/snippet 列表，无需 API Key。"""
    with httpx.Client(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        resp = client.get("https://html.duckduckgo.com/html/", params={"q": query})
        # 部分环境 html 端点只接受 POST 表单，GET 空结果时回退一次
        if resp.status_code >= 400 or "result__a" not in resp.text:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
        resp.raise_for_status()

    parser = _DDGResultParser()
    parser.feed(resp.text)
    return parser.results[:limit]


_TAG_RE = re.compile(r"<[^>]+>")
_ALGO_SPLIT = '<li class="b_algo"'


def _strip_tags(fragment: str) -> str:
    """去掉 HTML 标签并把实体转成可读文本。"""
    text = _TAG_RE.sub("", fragment)
    return " ".join(_html.unescape(text).split())


def _decode_bing_url(href: str) -> str:
    """把 Bing 的重定向链接还原成真实目标 URL。"""
    href = href.replace("&amp;", "&")
    parsed = urlparse(href)
    u = parse_qs(parsed.query).get("u", [""])[0]
    if u.startswith("a1"):
        try:
            pad = "=" * (-len(u[2:]) % 4)
            return base64.urlsafe_b64decode(u[2:] + pad).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            pass
    return href


def _bing_search(query: str, limit: int) -> list[dict]:
    """调用 Bing 网页搜索（无需 API Key），作为 DuckDuckGo 限流时的兜底。"""
    with httpx.Client(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        resp = client.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-hans", "count": str(limit)},
        )
        resp.raise_for_status()

    results: list[dict] = []
    for block in resp.text.split(_ALGO_SPLIT)[1:]:
        tm = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not tm:
            continue
        url = _decode_bing_url(tm.group(1))
        title = _strip_tags(tm.group(2))
        if not url or not title:
            continue
        sm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = _strip_tags(sm.group(1)) if sm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _web_search(query: str, limit: int) -> list[dict]:
    """先试 DuckDuckGo，被限流/空结果时回退 Bing，尽量保证搜索可用。"""
    try:
        results = _ddg_search(query, limit)
        if results:
            return results
    except Exception:  # noqa: BLE001
        pass
    return _bing_search(query, limit)


@tool
def browser_search(query: str, max_results: int = 5) -> str:
    """在互联网上搜索并返回结果摘要。用户问时事新闻、热点、某个话题的最新信息，或需要联网检索时调用本工具。

    Args:
        query: 搜索关键词，例如 '2024 年诺贝尔奖 得主'。
        max_results: 返回结果条数，默认 5，最多 10。
    """
    query = query.strip()
    if not query:
        return "Error: query 不能为空。"

    limit = max(1, min(int(max_results), 10))
    try:
        results = _web_search(query, limit)
    except Exception as e:  # noqa: BLE001
        return f"Error: 搜索失败: {e}"

    if not results:
        return (
            "未找到搜索结果，或搜索引擎暂时不可用。"
            "可尝试用 browser_fetch 直接访问已知的目标网站。"
        )

    lines = [f"搜索「{query}」结果："]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
