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
                title_el = card.xpath(".//div[contains(@class,'c-single-text')]")
                if not title_el:
                    title_el = card.xpath(".//a[contains(@class,'title')]")
                if not title_el:
                    continue
                title = title_el[0].text_content().strip()
                if not title:
                    continue
                hot_el = card.xpath(".//span[contains(@class,'hot-index')]")
                hot = hot_el[0].text_content().strip() if hot_el else ""
                desc_el = card.xpath(".//div[contains(@class,'c-summary')]")
                desc = desc_el[0].text_content().strip() if desc_el else ""
                items.append(normalize_item({
                    "title": title,
                    "url": f"https://www.baidu.com/s?wd={title}",
                    "source": "百度热搜",
                    "summary": f"{'🔥 ' + hot if hot else ''}{desc}"[:300],
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
        return f"OK, 获取到 {count} 条热搜"

    async def close(self):
        await self._http.aclose()
