"""Generic RSS/Atom feed source plugin."""
from xml.etree import ElementTree
import httpx
from datetime import datetime
from .base import BaseSource, normalize_item


class RSSSource(BaseSource):
    type_id = "rss"
    label = "RSS"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._max_items = self.config.get("max_items", 20)

    async def fetch(self) -> list[dict]:
        resp = await self._client.get(self.api_url)
        resp.raise_for_status()
        return self._apply_keywords(self._parse_feed(resp.text))

    def _parse_feed(self, xml_text: str) -> list[dict]:
        result = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return result

        # Handle RSS 2.0
        for channel in root.iter("channel"):
            for item in channel.iter("item"):
                entry = self._parse_rss_item(item)
                if entry:
                    result.append(entry)
                if len(result) >= self._max_items:
                    return result

        # Handle Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            entry = self._parse_atom_entry(entry, ns)
            if entry:
                result.append(entry)
            if len(result) >= self._max_items:
                return result

        return result

    def _parse_rss_item(self, item) -> dict:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        desc = item.findtext("description", "")
        pub = item.findtext("pubDate", "")
        source = item.findtext("source", "") or self.config.get("site_name", self.api_url)
        return normalize_item({
            "title": title.strip() if title else "",
            "url": link.strip() if link else "",
            "source": source.strip() if source else "",
            "summary": desc.strip()[:300] if desc else "",
            "publishedAt": pub.strip() if pub else "",
        }, default_source=source or self.api_url)

    def _parse_atom_entry(self, entry, ns) -> dict:
        title = entry.findtext("atom:title", "", ns)
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("atom:content", "", ns) or entry.findtext("atom:summary", "", ns)
        updated = entry.findtext("atom:updated", "", ns)
        author = entry.findtext("atom:author/atom:name", "", ns)
        return normalize_item({
            "title": title.strip() if title else "",
            "url": link.strip() if link else "",
            "source": author.strip() or self.config.get("site_name", self.api_url),
            "summary": summary.strip()[:300] if summary else "",
            "publishedAt": updated.strip() if updated else "",
        }, default_source=author or self.api_url)

    async def test(self) -> str:
        resp = await self._client.get(self.api_url)
        resp.raise_for_status()
        items = self._parse_feed(resp.text)
        return f"OK, parsed {len(items)} items from feed"

    async def close(self):
        await self._client.aclose()
