"""Source plugin to fetch content from various news sources."""
from abc import ABC, abstractmethod
from typing import Optional


class BaseSource(ABC):
    """Base class for news source plugins."""

    type_id: str = ""
    label: str = ""

    def __init__(self, api_url: str = "", api_key: str = "", config: Optional[dict] = None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.config = config or {}

    @abstractmethod
    async def fetch(self) -> list[dict]:
        """Fetch news items. Returns list of dicts with keys:
        title, url, source, summary, category, publishedAt
        """
        ...

    @abstractmethod
    async def test(self) -> str:
        """Test connection. Returns OK message or raises."""
        ...

    def _apply_keywords(self, items: list[dict]) -> list[dict]:
        """Filter items by title keywords from config."""
        return apply_keywords(items, self.config.get("filter_keywords", []))


def normalize_item(item: dict, default_source: str = "") -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", default_source),
        "summary": item.get("summary", ""),
        "category": item.get("category", "industry"),
        "publishedAt": item.get("publishedAt", ""),
    }


def apply_keywords(items: list[dict], keywords: list[str]) -> list[dict]:
    """Filter items, keeping only those whose title matches any keyword."""
    if not keywords or not items:
        return items or []
    kw_lower = [k.lower() for k in keywords if k.strip()]
    if not kw_lower:
        return items
    return [
        item for item in items
        if any(kw in (item.get("title") or "").lower() for kw in kw_lower)
    ]
