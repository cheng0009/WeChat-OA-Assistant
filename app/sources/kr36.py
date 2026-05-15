"""36氪快讯 source plugin."""
import json
import re
import httpx
from lxml import html as lh
from .base import BaseSource, normalize_item


class Kr36Source(BaseSource):
    type_id = "kr36"
    label = "36氪快讯"

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
            resp = await self._http.get("https://36kr.com/newsflashes")
            resp.raise_for_status()
        except Exception:
            return []
        items = []
        # Try embedded JSON in <script> tag
        data = self._extract_initial_state(resp.text)
        if data:
            for item in data.get("newsflashList", []):
                title = (item.get("title") or "").strip()
                url = item.get("news_url") or item.get("url", "")
                if not title:
                    continue
                items.append(normalize_item({
                    "title": title,
                    "url": url if "://" in url else f"https://36kr.com/p/{item.get('id', '')}",
                    "source": "36氪",
                    "summary": (item.get("summary") or item.get("description", ""))[:300],
                    "publishedAt": item.get("published_at", ""),
                }, default_source="36氪"))
        if items:
            return items
        # Fallback: parse HTML
        try:
            doc = lh.fromstring(resp.text)
            for card in doc.xpath("//div[contains(@class,'item')]"):
                title_el = card.xpath(".//a[contains(@class,'title')]")
                if not title_el:
                    continue
                title = title_el[0].text_content().strip()
                href = title_el[0].get("href", "")
                if not title:
                    continue
                full_url = href if "://" in href else f"https://36kr.com{href}"
                items.append(normalize_item({
                    "title": title,
                    "url": full_url,
                    "source": "36氪",
                }, default_source="36氪"))
        except Exception:
            pass
        return self._apply_keywords(items)

    def _extract_initial_state(self, html: str) -> dict | None:
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

    async def test(self) -> str:
        resp = await self._http.get("https://36kr.com/newsflashes")
        resp.raise_for_status()
        data = self._extract_initial_state(resp.text)
        if data:
            count = len(data.get("newsflashList", []))
            return f"OK, 获取到 {count} 条快讯"
        return "OK, 页面已加载但未发现快讯数据"

    async def close(self):
        await self._http.aclose()
