"""Find where the WeChat MP token is stored."""
import asyncio, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from app.config import BASE_DIR
from app.wechat_publisher import COOKIE_PATH

MP_URL = "https://mp.weixin.qq.com"

async def find_token():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800}, locale="zh-CN")
        page = await ctx.new_page()

        # Load cookies if exist
        if os.path.exists(COOKIE_PATH):
            with open(COOKIE_PATH, encoding="utf-8") as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)
            print(f"Loaded {len(cookies)} cookies")

        await page.goto(f"{MP_URL}/cgi-bin/home", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        if "/cgi-bin/home" not in page.url:
            print("Need login...")
            await page.goto(MP_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            print("Waiting QR scan...")
            await page.wait_for_url("**/cgi-bin/home**", timeout=120000)
            print("Login OK")

        # Save cookies
        cookies = await ctx.cookies()
        print(f"\n=== Cookies ({len(cookies)}) ===")
        for c in cookies:
            print(f"  {c['name']:30s} = {c['value'][:60]}")

        # Check localStorage
        ls = await page.evaluate("JSON.stringify(window.localStorage)")
        print(f"\n=== localStorage ===")
        print(f"  {ls[:500]}")

        # Check page for token in JS variables
        token_js = await page.evaluate("""() => {
            // Look for token in common JS variable names
            const patterns = ['token', 'Token', '_token', 'access_token'];
            const results = {};
            for (const key of patterns) {
                if (window[key] !== undefined) results['window.'+key] = window[key];
                // Check in global objects
                for (const obj of ['wx', 'mp', 'MM', 'WeixinJSBridge']) {
                    const o = window[obj];
                    if (o && o[key] !== undefined) results[obj+'.'+key] = o[key];
                }
            }
            return JSON.stringify(results);
        }""")
        print(f"\n=== JS token variables ===")
        print(f"  {token_js[:500]}")

        # Try to extract token from page HTML
        html = await page.content()
        import re
        # Look for token in various patterns
        patterns = [
            r'token["\']?\s*[:=]\s*["\']?(\d{5,15})',
            r'var\s+token\s*=\s*["\'](\d+)["\']',
            r'token:\s*["\'](\d+)["\']',
        ]
        print(f"\n=== Token in HTML ===")
        for p in patterns:
            for m in re.finditer(p, html):
                print(f"  Pattern '{p}': {m.group(1)}")

        # Navigate to a page that needs token and see URL
        print(f"\n=== Navigate to appmsg list ===")
        await page.goto(f"{MP_URL}/cgi-bin/appmsg?token=&lang=zh_CN", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"  URL: {page.url}")
        # Check if URL now has a token
        m = re.search(r"token=(\d+)", page.url)
        if m:
            print(f"  TOKEN FOUND IN URL: {m.group(1)}")

        await browser.close()

asyncio.run(find_token())
