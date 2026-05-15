"""掘金热门文章 source plugin."""
import httpx
from .base import BaseSource, normalize_item


class JuejinHotSource(BaseSource):
    type_id = "juejin_hot"
    label = "掘金热门"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(timeout=15)

    async def fetch(self) -> list[dict]:
        try:
            resp = await self._http.post(
                "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed?aid=2608",
                json={"id_type": 2, "client_type": 2608, "sort_type": 200},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items = []
        for entry in data.get("data", []):
            item_info = entry.get("item_info", entry)
            art = item_info.get("article_info", {})
            title = (art.get("title") or "").strip()
            article_id = item_info.get("article_id") or art.get("article_id", "")
            if not title or not article_id:
                continue
            author = item_info.get("author_user_info", {}).get("user_name", "")
            brief = (art.get("brief_content") or "").strip()
            items.append(normalize_item({
                "title": title,
                "url": f"https://juejin.cn/post/{article_id}",
                "source": f"掘金/{author}" if author else "掘金",
                "summary": brief,
            }, default_source="掘金"))
        return self._apply_keywords(items)

    async def test(self) -> str:
        resp = await self._http.post(
            "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed?aid=2608",
            json={"id_type": 2, "client_type": 2608, "sort_type": 200},
        )
        resp.raise_for_status()
        data = resp.json()
        count = len(data.get("data", []))
        return f"OK, 获取到 {count} 篇热门文章"

    async def close(self):
        await self._http.aclose()
