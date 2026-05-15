"""知乎日报 source plugin."""
from datetime import datetime
import httpx
from .base import BaseSource, normalize_item


class ZhihuDailySource(BaseSource):
    type_id = "zhihu_daily"
    label = "知乎日报"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(timeout=15)

    async def fetch(self) -> list[dict]:
        try:
            resp = await self._http.get("https://news-at.zhihu.com/api/4/news/latest")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items = []
        date_str = data.get("date", datetime.now().strftime("%Y%m%d"))
        for story in data.get("stories", []):
            title = (story.get("title") or "").strip()
            sid = story.get("id")
            if not title or not sid:
                continue
            hint = story.get("hint", "")
            items.append(normalize_item({
                "title": title,
                "url": f"https://daily.zhihu.com/story/{sid}",
                "source": "知乎日报",
                "summary": hint,
                "publishedAt": date_str,
            }, default_source="知乎日报"))
        return self._apply_keywords(items)

    async def test(self) -> str:
        resp = await self._http.get("https://news-at.zhihu.com/api/4/news/latest")
        resp.raise_for_status()
        data = resp.json()
        count = len(data.get("stories", []))
        return f"OK, 获取到 {count} 条日报"

    async def close(self):
        await self._http.aclose()
