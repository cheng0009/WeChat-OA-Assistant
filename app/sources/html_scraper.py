"""Generic web page scraper with auto-detection.

Supports three modes:
  auto (default): tries RSS discovery → auto-detect article links → single page
  list:           auto-detect article links from listing page
  single:         scrape one URL as a single article

All XPath fields are optional — when omitted, title/content/links are auto-detected.
"""
import re
from urllib.parse import urljoin
from xml.etree import ElementTree
import httpx
from lxml import html as lh
from .base import BaseSource, normalize_item

_ARTICLE_URL_PATTERNS = [
    r"/article/", r"/post/", r"/p/", r"/news/", r"/blog/",
    r"/item/", r"/story/", r"/detail/", r"/content/",
    r"/read/", r"/view/", r"/show/", r"/info/",
    r"/\d{4}/\d{2}/",
]

_NON_ARTICLE_PATTERNS = [
    r"/tag/", r"/category/", r"/author/", r"/login", r"/register",
    r"/signup", r"/password", r"/cart", r"/checkout",
    r"javascript:", r"^#", r"mailto:", r"tel:", r"/search",
    r"/page/\d+", r"/archive", r"/feed", r"/rss", r"/wp-",
    r"/about", r"/contact", r"/privacy", r"/terms",
]

_CONTENT_PATTERNS = [
    "//article",
    "//main",
    "//div[@class='content']",
    "//div[@id='content']",
    "//div[@class='post-content']",
    "//div[@class='article-content']",
    "//div[@class='entry-content']",
    "//div[contains(@class,'article')]",
    "//div[contains(@class,'post')]",
    "//div[contains(@class,'entry')]",
    "//div[@id='read-content']",
    "//section",
]

_TITLE_PATTERNS = [
    "//h1",
    "//article//h1",
    "//h2[@class='entry-title']",
    "//h2[contains(@class,'title')]",
    "//header//h1",
    "//head/title",
]


class HtmlScraperSource(BaseSource):
    type_id = "html_scraper"
    label = "任意网页（自动采集）"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        self.target_url = self.config.get("url", api_url)
        self.list_xpath = self.config.get("list_xpath", "")
        self.title_xpath = self.config.get("title_xpath", "")
        self.content_xpath = self.config.get("content_xpath", "")
        self.max_items = int(self.config.get("max_items", 10))
        self.mode = self.config.get("mode", "auto")

    async def fetch(self) -> list[dict]:
        if not self.target_url:
            return []

        if self.list_xpath:
            return self._apply_keywords(await self._fetch_list())

        if self.mode == "single":
            item = await self._fetch_single(self.target_url)
            return self._apply_keywords([item]) if item else []

        if self.mode == "list":
            return self._apply_keywords(await self._auto_detect_list())

        # auto mode: RSS → list → single
        items = await self._try_rss()
        if items:
            return self._apply_keywords(items)
        items = await self._auto_detect_list()
        if items:
            return self._apply_keywords(items)
        item = await self._fetch_single(self.target_url)
        return self._apply_keywords([item]) if item else []

    async def _try_rss(self) -> list[dict] | None:
        """Return RSS items if URL is a feed or page links to one."""
        html_text = await self._fetch_url(self.target_url)
        if not html_text:
            return None
        text = html_text.strip()

        if text.startswith("<?xml") or text.startswith("<rss") or text.startswith("<feed"):
            return self._parse_feed_text(text) or None

        try:
            doc = lh.fromstring(html_text)
        except Exception:
            return None

        feed_links = doc.xpath('//link[@type="application/rss+xml" or @type="application/atom+xml"]')
        if feed_links:
            href = feed_links[0].get("href", "")
            if href:
                feed_url = href if "://" in href else urljoin(self.target_url, href)
                feed_text = await self._fetch_url(feed_url)
                if feed_text:
                    result = self._parse_feed_text(feed_text)
                    if result:
                        return result
        return None

    def _parse_feed_text(self, text: str) -> list[dict]:
        items = []
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return items

        for channel in root.iter("channel"):
            for item in channel.iter("item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                desc = item.findtext("description", "").strip()
                pub = item.findtext("pubDate", "").strip()
                if title and link:
                    items.append(normalize_item({
                        "title": title, "url": link,
                        "summary": desc[:300], "content": desc,
                        "publishedAt": pub,
                    }, default_source=self._guess_site_name(self.target_url)))

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "").strip() if link_el is not None else ""
            summary = entry.findtext("atom:content", "", ns) or entry.findtext("atom:summary", "", ns)
            updated = entry.findtext("atom:updated", "", ns).strip()
            if title and link:
                items.append(normalize_item({
                    "title": title, "url": link,
                    "summary": summary.strip()[:300],
                    "publishedAt": updated,
                }, default_source=self._guess_site_name(self.target_url)))

        return items[:self.max_items]

    async def _fetch_list(self) -> list[dict]:
        html_text = await self._fetch_url(self.target_url)
        if not html_text:
            return []
        doc = lh.fromstring(html_text)
        links = doc.xpath(self.list_xpath)
        if not links:
            return []

        results = []
        seen_urls = set()
        for link_elem in links:
            if len(results) >= self.max_items:
                break
            href = link_elem.get("href", "").strip()
            if not href:
                continue
            full_url = href if "://" in href else urljoin(self.target_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            title = (link_elem.text or "").strip() or link_elem.get("title", "").strip()
            if not title:
                img = link_elem.find(".//img")
                if img is not None:
                    title = img.get("alt", "").strip()
            article = await self._fetch_single(full_url, fallback_title=title)
            if article:
                results.append(article)
        return results

    async def _auto_detect_list(self) -> list[dict]:
        html_text = await self._fetch_url(self.target_url)
        if not html_text:
            return []
        doc = lh.fromstring(html_text)
        all_links = doc.xpath("//a[@href]")
        scored = []
        for link in all_links:
            href = link.get("href", "").strip()
            text = (link.text_content() or "").strip()
            if len(text) < 4:
                continue
            full_url = href if "://" in href else urljoin(self.target_url, href)
            score = 0
            for pat in _ARTICLE_URL_PATTERNS:
                if re.search(pat, full_url):
                    score += 3
            for pat in _NON_ARTICLE_PATTERNS:
                if re.search(pat, full_url):
                    score -= 5
            parent = link.getparent()
            depth = 0
            while parent is not None and depth < 5:
                tag = parent.tag if isinstance(parent.tag, str) else ""
                if tag in ("h2", "h3", "h4", "h5"):
                    score += 2
                if tag in ("nav", "footer", "header", "aside"):
                    score -= 3
                parent = parent.getparent()
                depth += 1
            if 10 <= len(text) <= 200:
                score += 1
            if link.get("title", "").strip():
                score += 1
            if score > 0:
                scored.append((score, full_url, text))
        scored.sort(key=lambda x: -x[0])

        seen = set()
        results = []
        for score, url, title in scored:
            if len(results) >= self.max_items:
                break
            if url in seen:
                continue
            seen.add(url)
            article = await self._fetch_single(url, fallback_title=title)
            if article:
                results.append(article)
        return results

    async def _fetch_single(self, url: str, fallback_title="") -> dict | None:
        html_text = await self._fetch_url(url)
        if not html_text:
            return None
        doc = lh.fromstring(html_text)
        title = self._extract_title(doc) or fallback_title or url
        content_text = self._extract_content(doc)
        pub_date = self._extract_date(doc)
        return normalize_item({
            "title": title,
            "url": url,
            "source": self._guess_site_name(url),
            "summary": content_text[:300] if content_text else "",
            "content": content_text,
            "publishedAt": pub_date,
        }, default_source=self._guess_site_name(url))

    async def _fetch_url(self, url: str) -> str | None:
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "charset=" in content_type:
                resp.encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            return resp.text
        except Exception:
            return None

    def _extract_title(self, doc) -> str:
        if self.title_xpath:
            nodes = doc.xpath(self.title_xpath)
            if nodes:
                text = nodes[0].text_content().strip()
                if text:
                    return text
        for pat in _TITLE_PATTERNS:
            nodes = doc.xpath(pat)
            if nodes:
                text = nodes[0].text_content().strip()
                if text:
                    return text
        return ""

    def _extract_content(self, doc) -> str:
        if self.content_xpath:
            nodes = doc.xpath(self.content_xpath)
            if nodes:
                return self._clean_html(nodes[0])
        for pat in _CONTENT_PATTERNS:
            nodes = doc.xpath(pat)
            if nodes:
                text = self._clean_html(nodes[0])
                if len(text) > 100:
                    return text
        return ""

    def _extract_date(self, doc) -> str:
        date_pats = [
            "//time/@datetime",
            "//meta[@property='article:published_time']/@content",
            "//meta[@name='pubdate']/@content",
            "//span[contains(@class,'date')]/text()",
            "//span[contains(@class,'time')]/text()",
            "//em[@id='publish-time']/text()",
        ]
        for pat in date_pats:
            nodes = doc.xpath(pat)
            if nodes:
                val = str(nodes[0]).strip()
                if val:
                    return val
        return ""

    def _clean_html(self, element) -> str:
        for tag in element.xpath(".//script | .//style | .//nav | .//footer | .//aside"):
            tag.getparent().remove(tag)
        text = element.text_content()
        text = re.sub(r"\s+", " ", text).strip()
        return text[:5000]

    def _guess_site_name(self, url: str) -> str:
        m = re.match(r"https?://([^/]+)", url)
        return m.group(1) if m else url

    async def test(self) -> str:
        if not self.target_url:
            return "错误: 未设置网页 URL"
        try:
            resp = await self._http.get(self.target_url)
            resp.raise_for_status()
            text = resp.text.strip()
            is_rss = text.startswith("<?xml") or text.startswith("<rss") or text.startswith("<feed")
            if self.mode == "single":
                doc = lh.fromstring(text)
                title = self._extract_title(doc)
                content = self._extract_content(doc)
                parts = []
                if title:
                    parts.append(f"标题: {title[:40]}")
                parts.append(f"正文: {len(content)} 字符")
                return "OK, " + "，".join(parts)
            if self.list_xpath:
                doc = lh.fromstring(text)
                links = doc.xpath(self.list_xpath)
                return f"OK, 列表 XPath 匹配到 {len(links)} 个链接"
            if is_rss:
                items = self._parse_feed_text(text)
                return f"OK, 检测为 RSS 源，解析到 {len(items)} 条"
            doc = lh.fromstring(text)
            links = doc.xpath("//a[@href]")
            auto_count = min(len(links), 50)
            return f"OK, 页面已加载（{len(text)} 字节），自动检测到约 {auto_count} 个链接"
        except Exception as e:
            return f"失败: {type(e).__name__}: {e}"

    async def close(self):
        await self._http.aclose()
