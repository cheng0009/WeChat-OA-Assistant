"""V2EX 热帖 source plugin."""
from datetime import datetime
import httpx
from .base import BaseSource, normalize_item


class V2exHotSource(BaseSource):
    type_id = "v2ex_hot"
    label = "V2EX 热帖"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(timeout=15)

    async def fetch(self) -> list[dict]:
        try:
            resp = await self._http.get("https://www.v2ex.com/api/topics/hot.json")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items = []
        for topic in data:
            title = (topic.get("title") or "").strip()
            tid = topic.get("id")
            if not title or not tid:
                continue
            node_title = topic.get("node", {}).get("title", "")
            member = topic.get("member", {}).get("username", "")
            replies = topic.get("replies", 0)
            created_ts = topic.get("created", 0)
            pub = datetime.fromtimestamp(created_ts).isoformat() if created_ts else ""
            items.append(normalize_item({
                "title": title,
                "url": f"https://www.v2ex.com/t/{tid}",
                "source": f"V2EX/{node_title}" if node_title else "V2EX",
                "summary": f"👤 {member}  💬 {replies} 条回复" if member else f"💬 {replies} 条回复",
                "publishedAt": pub,
            }, default_source="V2EX"))
        return self._apply_keywords(items)

    async def test(self) -> str:
        resp = await self._http.get("https://www.v2ex.com/api/topics/hot.json")
        resp.raise_for_status()
        data = resp.json()
        return f"OK, 获取到 {len(data)} 条热帖"

    async def close(self):
        await self._http.aclose()
