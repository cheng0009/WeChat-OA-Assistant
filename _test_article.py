import asyncio
from app.database import init_db, async_session
from app.models import Article
from sqlalchemy import select

async def test():
    await init_db()
    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == 14))
        a = r.scalar_one_or_none()
        if a:
            print(f"Article: {a.id} {a.title[:20]}")
            print(f"wechat_draft_url: '{a.wechat_draft_url}'")
            print(f"wechat_media_ids: '{a.wechat_media_ids}'")
            print(f"wechat_published: {a.wechat_published}")
        else:
            print("Article not found")

asyncio.run(test())
