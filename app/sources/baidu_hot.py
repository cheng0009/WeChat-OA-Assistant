"""百度热搜 source plugin."""
from datetime import datetime
import httpx
from lxml import html as lh
from .base import BaseSource, normalize_item


class BaiduHotSource(BaseSource):
    type_id = "baidu_hot"
    label = "百度热搜"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    def _xpath_first(self, card, xpaths: list[str]):
        """尝试多个 XPath，返回第一个匹配到的元素"""
        for xp in xpaths:
            els = card.xpath(xp)
            if len(els) > 0:
                return els[0]
        return None

    async def fetch(self) -> list[dict]:
        try:
            resp = await self._http.get("https://top.baidu.com/board?tab=realtime")
            resp.raise_for_status()
        except Exception:
            return []
        items = []
        try:
            doc = lh.fromstring(resp.text)
            for card in doc.xpath("//div[contains(@class,'category-wrap')]"):
                title_el = self._xpath_first(card, [
                    ".//div[contains(@class,'c-single-text')]",
                    ".//span[contains(@class,'c-single-text-ellipsis')]",
                    ".//div[contains(@class,'title_')]",
                    ".//a[contains(@class,'title')]",
                ])
                if title_el is None:
                    continue
                title = title_el.text_content().strip()
                if not title:
                    continue

                hot_el = self._xpath_first(card, [
                    ".//div[contains(@class,'hot-index')]",
                    ".//span[contains(@class,'hot-index')]",
                ])
                hot = hot_el.text_content().strip() if hot_el is not None else ""

                desc_el = self._xpath_first(card, [
                    ".//div[contains(@class,'intro_')]",
                    ".//div[contains(@class,'hot-desc_')]",
                    ".//div[contains(@class,'c-summary')]",
                    ".//div[contains(@class,'desc_')]",
                ])
                desc = desc_el.text_content().strip() if desc_el is not None else ""

                items.append(normalize_item({
                    "title": title,
                    "url": f"https://www.baidu.com/s?wd={title}",
                    "source": "百度热搜",
                    "summary": f"{'🔥 ' + hot if hot else ''} {desc}"[:300],
                    "publishedAt": datetime.now().isoformat(),
                }, default_source="百度热搜"))
        except Exception:
            pass
        return self._apply_keywords(items)

    async def test(self) -> str:
        resp = await self._http.get("https://top.baidu.com/board?tab=realtime")
        resp.raise_for_status()
        doc = lh.fromstring(resp.text)
        count = len(doc.xpath("//div[contains(@class,'category-wrap')]"))
        if count == 0:
            return f"页面结构变化，请检查。当前获取到 0 条热搜"

        titles = []
        for card in doc.xpath("//div[contains(@class,'category-wrap')]")[:3]:
            title_el = self._xpath_first(card, [
                ".//div[contains(@class,'c-single-text')]",
                ".//span[contains(@class,'c-single-text-ellipsis')]",
                ".//div[contains(@class,'title_')]",
                ".//a[contains(@class,'title')]",
            ])
            if title_el is not None:
                titles.append(title_el.text_content().strip())

        return f"OK, 获取到 {count} 条热搜。前3条: {', '.join(titles) if titles else '无'}"

    async def close(self):
        await self._http.aclose()
