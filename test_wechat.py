"""
Test full publish flow: login → editor → title → upload → cover → desc → save.
"""
import asyncio, os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.wechat_publisher import WeChatPublisher
from app.config import BASE_DIR

TEST_DIR = str(BASE_DIR / "data" / "test_upload")
os.makedirs(TEST_DIR, exist_ok=True)

def create_images(n=3):
    from PIL import Image, ImageDraw, ImageFont
    fnt = None
    try: fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 40)
    except: pass
    files = []
    colors = [(41,98,255),(0,180,140),(255,70,70)]
    for i in range(n):
        img = Image.new("RGB", (800,600), colors[i])
        d = ImageDraw.Draw(img)
        if fnt: d.text((50,50), f"Test {i+1}", fill=(255,255,255), font=fnt)
        fp = os.path.join(TEST_DIR, f"t{i+1}.png")
        img.save(fp, "PNG")
        files.append(fp)
    return files

async def main():
    imgs = create_images()
    print(f"[Test] {len(imgs)} images ready")

    async with WeChatPublisher() as pub:
        token = await pub.ensure_login()
        print(f"[Test] Token: {token}")
        if "--login-only" in sys.argv: return

        # Open editor
        url = f"{pub.MP_URL}/cgi-bin/appmsg?action=edit&type=77&isNew=1&token={token}&lang=zh_CN"
        await pub._page.goto(url, wait_until="domcontentloaded")
        await pub._page.wait_for_timeout(5000)

        # Fill title
        el = await pub._page.wait_for_selector("#title", timeout=5000)
        if el:
            await el.click(); await el.fill(""); await el.fill("AI 热点测试")
        print("[Test] Title filled")

        # Upload images
        for i, fp in enumerate(imgs):
            fi = await pub._page.query_selector("input[type='file']")
            if not fi:
                await pub._page.evaluate("""()=>{
                    const e=document.createElement('input');
                    e.type='file'; e.id='__fu__';
                    e.style.cssText='position:fixed;left:0;top:0;z-index:99999;opacity:0';
                    e.accept='image/*'; document.body.appendChild(e);
                }""")
                fi = await pub._page.wait_for_selector("#__fu__", timeout=3000)
            if fi:
                await fi.set_input_files(fp)
                await pub._page.wait_for_timeout(6000)
        print("[Test] Upload done")

        # Set cover (calls _set_cover_from_content)
        await pub._set_cover_from_content()

        # Fill description
        text = "今日 AI 热点 OpenAI GPT-5 Gemini Ultra 2 国内大模型"[:120]
        de = await pub._page.wait_for_selector("#js_description", timeout=3000)
        if de:
            await de.click(); await de.fill(text)
        print("[Test] Desc filled")

        # Save
        sb = await pub._page.wait_for_selector("#js_submit button, button:has-text('保存为草稿')", timeout=5000)
        if sb:
            await sb.click()
            print("[Test] Saving...")
            for _ in range(30):
                await pub._page.wait_for_timeout(1000)
                m = re.search(r"appmsgid=(\d+)", pub._page.url)
                if m:
                    print(f"[OK] Draft saved! appmsgid={m.group(1)}")
                    return
        print("[FAIL] No draft URL")

if __name__ == "__main__":
    asyncio.run(main())
