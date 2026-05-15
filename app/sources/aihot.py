"""AI HOT (aihot.virxact.com) source plugin."""
from datetime import datetime, timedelta
import httpx
from .base import BaseSource, normalize_item


class AIHOTSource(BaseSource):
    type_id = "aihot"
    label = "AI HOT"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url or "https://aihot.virxact.com", api_key, config)
        ua = self.config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"User-Agent": ua},
            timeout=30,
        )

    async def _get_items(self, mode="selected", since=None, take=50):
        params = {"mode": mode, "take": take}
        if since:
            params["since"] = since
        resp = await self._client.get("/api/public/items", params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def _get_daily(self, date_str=None):
        ep = f"/api/public/daily/{date_str}" if date_str else "/api/public/daily"
        resp = await self._client.get(ep)
        resp.raise_for_status()
        return resp.json()

    async def fetch(self) -> list[dict]:
        since = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = await self._get_items(since=since, take=50)
        result = []
        for item in items:
            result.append(normalize_item(item, default_source="AI HOT"))
        return self._apply_keywords(result)

    async def test(self) -> str:
        items = await self._get_items(take=3)
        return f"OK, fetched {len(items)} items"

    async def close(self):
        await self._client.aclose()
