"""Aggregator fetcher: fetches from all enabled sources and merges results."""
import json
from datetime import datetime
from sqlalchemy import select
from app.database import async_session
from app.models import Source
from app.sources import get_source, get_source_class


async def fetch_from_all_sources() -> list[dict]:
    """Fetch from all enabled DB sources, merged & deduplicated by URL."""
    all_items = []
    seen_urls = set()

    async with async_session() as session:
        result = await session.execute(
            select(Source).where(Source.enabled == True)
        )
        sources = result.scalars().all()

    for src_row in sources:
        try:
            cls = get_source_class(src_row.source_type)
            config = {}
            try:
                config = json.loads(src_row.config) if src_row.config else {}
            except json.JSONDecodeError:
                pass
            instance = cls(
                api_url=src_row.api_url,
                api_key=src_row.api_key or "",
                config=config,
            )
            items = await instance.fetch()
            for item in items:
                url = item.get("url", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                all_items.append(item)
            # Update last_fetch
            async with async_session() as upd:
                row = await upd.execute(select(Source).where(Source.id == src_row.id))
                s = row.scalar_one_or_none()
                if s:
                    s.last_fetch_at = datetime.utcnow()
                    s.last_fetch_ok = True
                    await upd.commit()
            if hasattr(instance, "close"):
                await instance.close()
        except Exception as e:
            print(f"[Fetcher] Source {src_row.name} ({src_row.source_type}) failed: {e}")
            async with async_session() as upd:
                row = await upd.execute(select(Source).where(Source.id == src_row.id))
                s = row.scalar_one_or_none()
                if s:
                    s.last_fetch_ok = False
                    await upd.commit()

    return all_items


async def test_source(source_id: int) -> str:
    """Test a single source, return result message."""
    async with async_session() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        src = result.scalar_one_or_none()
        if not src:
            return "Source not found"
        try:
            cls = get_source_class(src.source_type)
            config = {}
            try:
                config = json.loads(src.config) if src.config else {}
            except json.JSONDecodeError:
                pass
            instance = cls(api_url=src.api_url, api_key=src.api_key or "", config=config)
            msg = await instance.test()
            if hasattr(instance, "close"):
                await instance.close()
            return msg
        except Exception as e:
            return f"Error: {e}"
