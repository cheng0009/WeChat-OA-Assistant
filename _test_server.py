import asyncio
import traceback
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import init_db

async def test():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.get("/articles/14")
        print(f"Status: {r.status_code}")
        if r.status_code != 200:
            print(f"Response body: {r.text[:2000]}")

asyncio.run(test())
