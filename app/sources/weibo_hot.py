"""微博热搜 source plugin."""
from datetime import datetime
import httpx
from .base import BaseSource, normalize_item


class WeiboHotSource(BaseSource):
    type_id = "weibo_hot"
    label = "微博热搜"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://weibo.com/",
            },
        )

    async def fetch(self) -> list[dict]:
        try:
            resp = await self._http.get("https://weibo.com/ajax/side/hotSearch")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items = []
        now = datetime.now().isoformat()
        for item in data.get("data", {}).get("realtime", []):
            title = (item.get("word") or "").strip()
            if not title:
                continue
            raw_hot = item.get("raw_hot", "")
            items.append(normalize_item({
                "title": title,
                "url": f"https://s.weibo.com/weibo?q=%23{title}%23",
                "source": "微博热搜",
                "summary": f"热度: {raw_hot}" if raw_hot else "",
                "publishedAt": now,
            }, default_source="微博热搜"))
        return self._apply_keywords(items)

    async def test(self) -> str:
        resp = await self._http.get("https://weibo.com/ajax/side/hotSearch")
        resp.raise_for_status()
        data = resp.json()
        count = len(data.get("data", {}).get("realtime", []))
        return f"OK, 获取到 {count} 条热搜"

    async def close(self):
        await self._http.aclose()
