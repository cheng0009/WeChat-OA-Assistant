"""Login and explore WeChat MP sticker page."""
import asyncio, os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fix stdout encoding
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

from playwright.async_api import async_playwright
from app.config import BASE_DIR
from app.wechat_publisher import COOKIE_PATH

MP_URL = "https://mp.weixin.qq.com"
OUT = str(BASE_DIR / "data" / "wechat_debug")
os.makedirs(OUT, exist_ok=True)

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800}, locale="zh-CN")
        page = await ctx.new_page()

        # Load cookie if exists
        if os.path.exists(COOKIE_PATH):
            with open(COOKIE_PATH, encoding="utf-8") as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)
            print(f"[Login] Loaded {len(cookies)} cookies")

        # Login
        await page.goto(f"{MP_URL}/cgi-bin/home", wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Check if logged in (look for sidebar menu)
        menu_loaded = await page.evaluate("document.querySelectorAll('.weui-desktop-menu').length > 0")
        
        if not menu_loaded and "/cgi-bin/home" not in page.url:
            print("[Login] Need QR scan...")
            await page.goto(MP_URL, wait_until="networkidle")
            await page.wait_for_timeout(2000)
            deadline = time.time() + 120
            while time.time() < deadline:
                if "/cgi-bin/home" in page.url:
                    await page.wait_for_timeout(3000)
                    break
                await page.wait_for_timeout(1000)
        
        # Save cookie
        cookies = await ctx.cookies()
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False)
        print(f"[Login] Cookie saved ({len(cookies)} cookies)")

        # Extract token
        token = ""
        m = re.search(r'token=(\d+)', page.url)
        if m: token = m.group(1)
        print(f"[Login] Token: {token}")
        print(f"[Login] URL: {page.url}")

        # Get all sidebar menu items
        menu_items = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.weui-desktop-menu__link, .menu_item, [class*="menu"] a')).map(a => ({
                text: (a.textContent || '').trim().slice(0, 40),
                href: (a.href || '').slice(0, 250)
            }));
        }""")
        print(f"\n[Menu] Items ({len(menu_items)}):")
        for item in menu_items:
            if item['text']:
                print(f"  '{item['text']}' -> {item['href']}")

        # Search for 贴图/表情/sticker in all links
        all_text = await page.evaluate("document.body.innerText")
        
        # Save full HTML
        html = await page.content()
        with open(os.path.join(OUT, "home_logged_in.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n[Save] HTML saved to data/wechat_debug/home_logged_in.html")

        # Search for sticker-related keywords
        for keyword in ['贴图', '表情', 'sticker', '素材']:
            if keyword in all_text:
                print(f"[Found] '{keyword}' in page text")

        # Try known URLs
        urls_to_try = [
            f"{MP_URL}/cgi-bin/appmsg?action=list&type=77&token={token}&lang=zh_CN",
        ]
        
        for url in urls_to_try:
            print(f"\n[Trying] {url[:120]}")
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            print(f"  -> URL: {page.url}")
            
            # Dump buttons
            btns = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button, a')).slice(0,30).map(e => ({
                    text: (e.textContent || '').trim().slice(0,30),
                    tag: e.tagName,
                    cls: (e.className || '').slice(0,60),
                    href: e.href ? e.href.slice(0,150) : ''
                }));
            }""")
            for b in btns:
                if b['text']:
                    print(f"  btn: '{b['text']}' cls={b['cls']}")

        await page.wait_for_timeout(5000)
        print("\n[Done] Browser will close. Press Ctrl+C to skip wait.")
        await asyncio.sleep(10)
        await browser.close()

asyncio.run(main())
