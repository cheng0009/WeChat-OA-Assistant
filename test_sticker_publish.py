"""Publish sticker (tietu) for a given article. Usage: python test_sticker_publish.py <article_id> [channel_id]"""
import asyncio
import sys, json, os, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import BASE_DIR
from app.database import async_session
from app.models import Article
from sqlalchemy import select

# ── Config ──────────────────────────────────────────────────────────
MP_URL = "https://mp.weixin.qq.com"

ARTICLE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if not ARTICLE_ID:
    print("Usage: python test_sticker_publish.py <article_id> [channel_id]")
    sys.exit(1)

CHANNEL_ID = int(sys.argv[2]) if len(sys.argv) > 2 else 0


async def main():

    # 1. Load article from database
    async with async_session() as db:
        result = await db.execute(select(Article).where(Article.id == ARTICLE_ID))
        article = result.scalar_one_or_none()
    if not article:
        print(f"[FAIL] Article {ARTICLE_ID} not found in database")
        return
    print(f"[INFO] Article: {article.title[:50]}...")
    print(f"[INFO] Sticker images: {article.wechat_images[:80]}...")

    # Build a dict-like access for the rest of the script
    article_data = {
        "title": article.title,
        "viral_title": article.viral_title or article.title,
        "wechat_images": article.wechat_images or "",
        "sticker_content": article.sticker_content or "",
        "channel_id": article.channel_id,
        "id": article.id,
    }

    # 2. Resolve local image paths
    wechat_images_str = article_data["wechat_images"]
    if not wechat_images_str:
        print("[FAIL] No wechat_images found for this article")
        return
    image_urls = wechat_images_str.split(",")
    print(f"[INFO] Found {len(image_urls)} images")

    local_paths = []
    for img_url in image_urls[:1]:  # Only test with 1 image
        path = _resolve_path(img_url)
        if path and os.path.exists(path):
            local_paths.append(path)
            print(f"[INFO] Image {len(local_paths)}: {path}")
        else:
            print(f"[WARN] Image not found: {img_url} -> {path}")

    if not local_paths:
        print("[FAIL] No local images found")
        return

    # Use channel_id from article if not specified on command line
    channel_id = CHANNEL_ID or article_data["channel_id"] or 0
    print(f"[INFO] Using channel_id={channel_id}")

    # 3. Run Playwright to test sticker publishing
    from playwright.async_api import async_playwright
    suffix = f"_{channel_id}" if channel_id else ""
    state_path = str(BASE_DIR / "data" / f"wechat_state{suffix}.json")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])

        storage = state_path if os.path.exists(state_path) else None
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            storage_state=storage,
        )
        page = await context.new_page()

        print("\n=== Step 1: Ensure login and get token ===")
        # Navigate to WeChat MP homepage
        try:
            await page.goto(f"{MP_URL}/cgi-bin/home", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        # Check if logged in - may fail if page navigated during query, so retry
        for attempt in range(3):
            try:
                logged_in = await page.query_selector(
                    ".weui-desktop-account__info, .weui-desktop-menu_global, #menu_10125"
                )
                break
            except Exception:
                # Page navigated, retry after a moment
                await page.wait_for_timeout(1000)
                continue
        token = _extract_token(page.url)
        if not logged_in and not token:
            print("[WAIT] Not logged in. Scan QR code to login...")
            # Poll URL for token instead of wait_for_url (navigation may already have happened)
            deadline = time.time() + 120
            while time.time() < deadline:
                token = _extract_token(page.url)
                if token:
                    break
                await page.wait_for_timeout(2000)
            if not token:
                print("[FAIL] Login timeout")
                await browser.close()
                return False
            print(f"[OK] Logged in, token={token}")
            # Save session state for future use
            state = await context.storage_state()
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f)
            print("[OK] Session saved")
        else:
            print(f"[OK] Already logged in, token={token}")

        # Now navigate to sticker editor with real token
        editor_url = (
            f"{MP_URL}/cgi-bin/appmsg"
            f"?t=media/appmsg_edit_v2&action=edit&isNew=1"
            f"&type=77&createType=8"
            + (f"&token={token}" if token else "")
            + f"&lang=zh_CN&timestamp={int(time.time() * 1000)}"
        )
        await page.goto(editor_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        print(f"\n=== Step 2: Sticker editor loaded ===")
        print(f"URL: {page.url[:120]}...")
        await _dump_page_info(page)

        # Setup network monitor to capture upload responses
        _setup_upload_monitor(page)

        # 4. Try uploading images
        print(f"\n=== Step 3: Upload 1 sticker image ===")
        for local_path in local_paths:
            print(f"\n  Trying to upload: {os.path.basename(local_path)}")
            ok = await _try_upload(page, local_path)
            if ok:
                print(f"  [OK] Uploaded!")
                await page.wait_for_timeout(3000)
                break
            else:
                print(f"  [FAIL] Upload failed, trying next strategy...")
                await page.wait_for_timeout(1000)

        # If upload went to media library instead of editor, inject images via JS
        if _uploaded_media:
            print(f"\n  Media URLs from network: {_uploaded_media[:3]}...")
            injected = await page.evaluate(f"""() => {{
                const container = document.querySelector('.image-selector__add, .image-selector, .appmsg_image_area');
                if (!container) return 'no container';
                const urls = {json.dumps(_uploaded_media[:7])};
                for (const url of urls) {{
                    const img = document.createElement('img');
                    img.src = url;
                    img.style.cssText = 'max-width:200px;max-height:200px;margin:4px;border-radius:4px';
                    container.appendChild(img);
                }}
                return 'injected ' + urls.length + ' images';
            }}""")
            print(f"  Image injection: {injected}")

        # 5. Fill title
        print(f"\n=== Step 4: Fill title ===")
        sticker_title = article_data["viral_title"][:20]
        ok = await _try_fill_title(page, sticker_title)
        print(f"  Title: {'[OK]' if ok else '[FAIL]'} '{sticker_title}'")

        # 6. Fill description
        print(f"\n=== Step 5: Fill description ===")
        sticker_content = article_data["sticker_content"]
        if sticker_content:
            ok = await _try_fill_description(page, sticker_content[:120])
            print(f"  Description: {'[OK]' if ok else '[FAIL]'}")
        else:
            print(f"  Skipped (no sticker_content)")

        # 7. Save draft
        print(f"\n=== Step 6: Save draft ===")
        await page.wait_for_timeout(2000)

        # Handle reward/tip setting if present
        reward_area = await page.query_selector("#js_reward_setting_area")
        if reward_area:
            # If "不开启" is shown, reward is OFF → click it to open dialog → confirm to enable
            no_open_text = await reward_area.query_selector("text=不开启")
            if no_open_text:
                print(f"  [OK] Reward is OFF, clicking to enable...")
                try:
                    await no_open_text.click()
                    await page.wait_for_timeout(800)
                    # Dialog appeared: click "确定" to confirm
                    confirm_btn = page.get_by_role("button", name="确定")
                    if await confirm_btn.is_visible():
                        await confirm_btn.click()
                        await page.wait_for_timeout(500)
                        print(f"  [OK] Reward enabled")
                except Exception:
                    pass
            else:
                print(f"  [OK] Reward already ON, skipping")

        save_clicked = False
        # Codegen: use get_by_role("button", name="保存为草稿")
        try:
            save_btn = page.get_by_role("button", name="保存为草稿")
            if await save_btn.is_visible():
                await save_btn.click()
                print(f"  [OK] Clicked save button")
                save_clicked = True
        except Exception:
            pass
        if not save_clicked:
            for sel in ["#js_submit button", "#js_save_btn", "button:has-text('保存为草稿')",
                         "button.weui-desktop-btn_primary:not(.weui-desktop-btn_disabled)",
                         "a:has-text('提交保存')"]:
                try:
                    btn = await page.wait_for_selector(sel, timeout=2000)
                    if btn and await btn.is_visible() and await btn.is_enabled():
                        await btn.click()
                        print(f"  [OK] Clicked save: '{sel}'")
                        save_clicked = True
                        break
                except Exception:
                    continue
        if not save_clicked:
            print("  [WARN] Could not find save button, you may need to click manually")

        print("  [WAIT] Waiting for draft to save (detecting appmsgid in URL)...")
        for _ in range(30):
            current_url = page.url
            m = re.search(r"appmsgid=(\d+)", current_url)
            if m:
                print(f"\n  [OK] Draft saved! appmsgid={m.group(1)}")
                preview = f"{MP_URL}/cgi-bin/appmsg?token={_extract_token(page.url)}&lang=zh_CN&type=77&action=edit&appmsgid={m.group(1)}"
                print(f"  Preview URL: {preview}")
                break
            await page.wait_for_timeout(1000)
        else:
            print("\n  [INFO] No auto-save detected. Manual check needed.")

        print("\n=== Test complete ===")
        await page.wait_for_timeout(5000)
        await context.close()
        await browser.close()


# ── Helper functions ─────────────────────────────────────────────────

def _resolve_path(img_url: str) -> str | None:
    """Convert web URL like /data/wechat/folder/01-title.png to local file path."""
    path = (img_url or "").strip()
    if not path:
        return None
    if os.path.exists(path):
        return path
    wechat_dir = str(BASE_DIR / "data" / "wechat")
    rel = path.replace("/data/wechat/", "").replace("\\", "/")
    full = os.path.join(wechat_dir, rel)
    if os.path.exists(full):
        return full
    images_dir = str(BASE_DIR / "data" / "images")
    rel2 = path.replace("/data/images/", "").replace("\\", "/")
    full2 = os.path.join(images_dir, rel2)
    if os.path.exists(full2):
        return full2
    return None


def _extract_token(url: str) -> str:
    m = re.search(r"[?&]token=(\d+)", url)
    return m.group(1) if m else ""


# Track upload responses for media_id extraction
_uploaded_media = []


def _setup_upload_monitor(page):
    """Intercept WeChat upload API responses to capture media_id."""
    _uploaded_media.clear()

    async def handle_response(response):
        url = response.url
        if "filetransfer" in url or "appmsg" in url or "upload" in url:
            try:
                body = await response.text()
                # WeChat responses are typically JSON with content/media_id
                import json as _json
                data = _json.loads(body)
                content = data.get("content") or data.get("media_id") or ""
                if content:
                    _uploaded_media.append(content)
                    print(f"    [NET] Upload response: content={str(content)[:80]}")
            except Exception:
                pass

    page.on("response", handle_response)


async def _dump_page_info(page):
    """Print key page elements for debugging."""
    import json
    info = await page.evaluate("""() => {
        const els = document.querySelectorAll('button, a, input, textarea, [contenteditable], .upload-area, [class*=upload], [class*=image]');
        return Array.from(els).slice(0, 40).map(e => ({
            tag: e.tagName,
            id: e.id || '',
            cls: (e.className || '').slice(0, 50),
            txt: (e.textContent || '').trim().slice(0, 40),
            type: e.type || '',
            visible: e.offsetParent !== null,
            placeholder: e.placeholder || '',
        }));
    }""")
    for el in info:
        vis = "V" if el["visible"] else "H"
        print(f"  [{vis}] <{el['tag']} #{el['id']} .{el['cls']}> {el['txt'][:40]}")


async def _try_upload(page, filepath: str) -> bool:
    """Upload image to sticker editor using WebUploader's picker."""
    filename = os.path.basename(filepath)
    print(f"    Uploading {filename}...")

    # Count existing mmbiz images before upload (to detect new ones after)
    pre_count = 0
    pre_imgs = await page.query_selector_all("img[src*='mmbiz']")
    pre_count = len(pre_imgs)

    # Strategy 1: Click .webuploader-pick with mouse (real click event)
    print(f"    Strategy 1: mouse click on webuploader-pick...")
    picker = page.locator(".webuploader-pick").first
    if await picker.count() > 0:
        try:
            bbox = await picker.bounding_box()
            if bbox:
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await page.mouse.click(
                        bbox['x'] + bbox['width'] / 2,
                        bbox['y'] + bbox['height'] / 2,
                    )
                fc = await fc_info.value
                await fc.set_files(filepath)
                print(f"    Files set via file chooser, waiting for upload...")
                await page.wait_for_timeout(3000)
                # Check for NEW mmbiz images
                new_imgs = await page.query_selector_all("img[src*='mmbiz']")
                if len(new_imgs) > pre_count:
                    print(f"    [OK] Upload confirmed (new mmbiz image)")
                    return True
        except Exception as e:
            print(f"    webuploader-pick mouse click: {type(e).__name__}")

    # Strategy 2: Click "本地上传" text element
    print(f"    Strategy 2: click 本地上传 text...")
    for i in range(min(10, await page.locator("text=本地上传").count())):
        el = page.locator("text=本地上传").nth(i)
        if await el.is_visible():
            try:
                bbox = await el.bounding_box()
                if bbox:
                    async with page.expect_file_chooser(timeout=8000) as fc_info:
                        await page.mouse.click(
                            bbox['x'] + bbox['width'] / 2,
                            bbox['y'] + bbox['height'] / 2,
                        )
                    fc = await fc_info.value
                    await fc.set_files(filepath)
                    print(f"    Files set via 本地上传 #{i}, waiting...")
                    await page.wait_for_timeout(3000)
                    new_imgs = await page.query_selector_all("img[src*='mmbiz']")
                    if len(new_imgs) > pre_count:
                        print(f"    [OK] Upload confirmed via 本地上传 #{i}")
                        return True
            except Exception as e:
                print(f"    本地上传 #{i}: {type(e).__name__}")
                continue

    # Strategy 3: Click a.pop-opr__button 本地上传 with mouse
    print(f"    Strategy 3: click a.pop-opr__button...")
    for i in range(await page.locator("a.pop-opr__button").count()):
        btn = page.locator("a.pop-opr__button").nth(i)
        text = await btn.text_content() or ""
        if text.strip() == "本地上传" and await btn.is_visible():
            try:
                bbox = await btn.bounding_box()
                if bbox:
                    async with page.expect_file_chooser(timeout=8000) as fc_info:
                        await page.mouse.click(
                            bbox['x'] + bbox['width'] / 2,
                            bbox['y'] + bbox['height'] / 2,
                        )
                    fc = await fc_info.value
                    print(f"    File dialog captured, setting file: {os.path.basename(filepath)}")
                    await fc.set_files(filepath)
                    await page.wait_for_timeout(300)
                    # Click body to close popover and trigger WeChat upload handler
                    await page.mouse.click(100, 100)
                    await page.wait_for_timeout(1000)
                    # Dispatch change on ALL file inputs to ensure WebUploader sees it
                    await page.evaluate("""() => {
                        document.querySelectorAll('input[type="file"]').forEach(el => {
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        });
                    }""")
                    await page.wait_for_timeout(5000)
                    new_imgs = await page.query_selector_all("img[src*='mmbiz']")
                    if len(new_imgs) > pre_count:
                        print(f"    [OK] Upload confirmed via a.pop-opr__button")
                        return True
                    print(f"    No new mmbiz image (pre={pre_count}, now={len(new_imgs)})")
            except Exception as e:
                print(f"    a.pop-opr__button: {type(e).__name__}: {e}")
                continue

    # Strategy 4: Make file input visible + set files + dispatch change
    print(f"    Strategy 4: visible file input + set_files...")
    file_input = await page.query_selector("input[type='file']")
    if file_input:
        await page.evaluate("""(el) => {
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.position = 'fixed';
            el.style.top = '0';
            el.style.left = '0';
            el.style.zIndex = '99999';
            el.style.opacity = '0.01';
            el.style.width = '300px';
            el.style.height = '50px';
        }""", file_input)
        await page.wait_for_timeout(300)
        try:
            await file_input.set_input_files(filepath)
            await page.wait_for_timeout(3000)
            # Dispatch change event on the file input
            await page.evaluate("""() => {
                const inp = document.querySelector('input[type="file"]');
                if (inp) inp.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
            await page.wait_for_timeout(5000)
            # Check for NEW mmbiz images
            new_imgs = await page.query_selector_all("img[src*='mmbiz']")
            if len(new_imgs) > pre_count:
                print(f"    [OK] Upload confirmed via visible file input")
                # Restore styles
                await page.evaluate("""(el) => {
                    el.style.display = ''; el.style.visibility = '';
                    el.style.position = ''; el.style.top = '';
                    el.style.left = ''; el.style.zIndex = '';
                    el.style.opacity = ''; el.style.width = ''; el.style.height = '';
                }""", file_input)
                return True
            # Restore styles
            await page.evaluate("""(el) => {
                el.style.display = ''; el.style.visibility = '';
                el.style.position = ''; el.style.top = '';
                el.style.left = ''; el.style.zIndex = '';
                el.style.opacity = ''; el.style.width = ''; el.style.height = '';
            }""", file_input)
        except Exception as e:
            print(f"    set_input_files: {type(e).__name__}")

    # Strategy 5: Read file as base64, inject via JS into WebUploader's file input
    print(f"    Strategy 5: base64 file injection...")
    try:
        import base64
        with open(filepath, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode()
        print(f"    Read {len(b64_data)} base64 chars from {os.path.basename(filepath)}")
        injected = await page.evaluate("""({b64, name}) => {
            const byteChars = atob(b64);
            const byteArray = new Uint8Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) byteArray[i] = byteChars.charCodeAt(i);
            const blob = new Blob([byteArray], {type: 'image/png'});
            const file = new File([blob], name, {type: 'image/png'});
            const dt = new DataTransfer();
            dt.items.add(file);

            // Find WebUploader's file input (the first one on the page)
            const inputs = document.querySelectorAll('input[type="file"]');
            if (inputs.length === 0) return 'no file input';
            // Try each input
            for (const inp of inputs) {
                try {
                    inp.files = dt.files;
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                } catch(e) {
                    // continue
                }
            }
            return 'injected:' + inputs.length + ' inputs';
        }""", {"b64": b64_data, "name": filename})
        print(f"    Injection result: {injected}")
        await page.wait_for_timeout(5000)
        new_imgs = await page.query_selector_all("img[src*='mmbiz']")
        if len(new_imgs) > pre_count:
            print(f"    [OK] Upload confirmed via base64 injection")
            return True
    except Exception as e:
        print(f"    base64 injection failed: {type(e).__name__}: {e}")

    print(f"    [FAIL] No new mmbiz image detected")
    return False


async def _try_fill_title(page, text: str) -> bool:
    """Fill title in sticker editor. Codegen confirms: #js_title_main div:nth(3) (contenteditable)."""
    text = text[:20]
    # Strategy 1: Use locator nth(3) as Codegen shows
    title_locator = page.locator("#js_title_main div").nth(3)
    try:
        if await title_locator.count() > 0:
            await title_locator.click()
            await page.wait_for_timeout(300)
            await title_locator.fill("")
            await title_locator.fill(text)
            print(f"    [OK] Title filled via #js_title_main div:nth(3)")
            return True
    except Exception:
        pass
    # Strategy 2: First contenteditable inside #js_title_main
    title_div = await page.query_selector("#js_title_main div[contenteditable]")
    if title_div:
        try:
            await title_div.click()
            await page.wait_for_timeout(300)
            await title_div.fill("")
            await title_div.fill(text)
            print(f"    [OK] Title filled via #js_title_main div[contenteditable]")
            return True
        except Exception:
            pass
    # Strategy 3: hidden #title input
    title_input = await page.query_selector("#title")
    if title_input:
        try:
            await title_input.fill(text)
            print(f"    [OK] Title filled via #title input")
            return True
        except Exception:
            pass
    # Strategy 4: evaluate fallback
    filled = await page.evaluate(f"""() => {{
        const el = document.querySelector('#js_title_main div, #title, .js_title, input[name=title]');
        if (el) {{
            el.focus();
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
                el.value = {json.dumps(text)};
            }} else {{
                el.innerText = {json.dumps(text)};
            }}
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }}
        return false;
    }}""")
    if filled:
        print(f"    [OK] Title filled via evaluate")
    return filled


async def _try_fill_description(page, text: str) -> bool:
    """Fill description in sticker editor. Codegen: div with placeholder text."""
    text = text[:120]
    # Strategy 1: div with placeholder text (sticker editor)
    desc_div = page.locator("div").filter(has_text=re.compile(r"^填写描述信息")).first
    if desc_div:
        try:
            await desc_div.click()
            await page.wait_for_timeout(300)
            await desc_div.fill(text)
            print(f"    [OK] Description filled via placeholder div")
            return True
        except Exception:
            pass
    # Strategy 2: known description selectors
    for sel in ["#js_description", ".rich_media_content", ".js_appmsg_desc",
                "textarea[name='description']", ".appmsg_description"]:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            if el:
                await el.click()
                await page.wait_for_timeout(300)
                await el.fill(text)
                print(f"    [OK] Filled via '{sel}'")
                return True
        except Exception:
            continue
    # Strategy 3: evaluate fallback
    filled = await page.evaluate(f"""() => {{
        const edits = document.querySelectorAll('[contenteditable=true], textarea, .rich_media_content');
        for (const el of edits) {{
            if (el.offsetParent === null) continue;
            // Skip if this looks like a title area
            if (el.closest('#js_title_main, .js_title, #title')) continue;
            el.focus();
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
                el.value = {json.dumps(text)};
            }} else {{
                el.innerText = {json.dumps(text)};
            }}
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }}
        return false;
    }}""")
    if filled:
        print(f"    [OK] Description filled via evaluate")
    else:
        print(f"    [WARN] Could not find description field")
    return filled


if __name__ == "__main__":
    asyncio.run(main())
