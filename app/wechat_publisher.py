"""
Playwright-based WeChat Article Publisher (type=77, image-message editor).

Flow:
  1. Launch browser -> load/ensure login (cookie persist)
  2. Navigate to sticker editor (createType=8)
  3. Upload sticker images via file chooser
  4. Fill title & description -> save draft
  5. Return draft URL
"""
import asyncio
import json, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from app.models import Article
from app.config import DATA_DIR


class LoginRequiredError(RuntimeError):
    """Raised when WeChat login is required but headless mode is active."""


def _get_chromium_path() -> Optional[str]:
    """Return path to bundled Chromium when running as frozen exe."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(os.path.dirname(sys.executable))
        candidates = [
            exe_dir / "chrome-win" / "chrome.exe",
            exe_dir / "chrome-win64" / "chrome.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return None


class WeChatPublisher:
    MP_URL = "https://mp.weixin.qq.com"

    def __init__(self, channel_id: int = 0, headless: bool = False):
        self.channel_id = channel_id
        self.headless = headless
        suffix = f"_{channel_id}" if channel_id else ""
        self.cookie_path = str(DATA_DIR / f"wechat_cookies{suffix}.json")
        self.state_path = str(DATA_DIR / f"wechat_state{suffix}.json")
        self._pw = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        chrome_path = _get_chromium_path()
        launch_kwargs = dict(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        storage_state = self.state_path if os.path.exists(self.state_path) else None
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            storage_state=storage_state,
        )
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Login ────────────────────────────────────────────────

    async def ensure_login(self):
        """Check login state, auto-re-login if session expired."""
        await self._page.goto(f"{self.MP_URL}/cgi-bin/home", wait_until="domcontentloaded")
        await self._page.wait_for_timeout(5000)

        token = self._extract_token()
        logged_in_selectors = [
            ".weui-desktop-account__info",
            ".weui-desktop-menu_global",
            "#menu_10125",
            ".js_global_menu",
        ]
        has_logged_in_ui = False
        for sel in logged_in_selectors:
            try:
                if await self._page.query_selector(sel):
                    has_logged_in_ui = True
                    break
            except Exception:
                continue

        login_required = not token and not has_logged_in_ui
        if not login_required:
            await self._persist_session()
            return token

        if self.headless:
            raise LoginRequiredError(
                "WeChat login required but running in headless mode. "
                "Please login manually via the channel settings page."
            )

        print("[WeChat] Session expired, auto-clicking login button...")
        for text in ["重新登录", "登录"]:
            try:
                btn = self._page.get_by_text(text, exact=True)
                if await btn.count() > 0 and await btn.first.is_visible():
                    await btn.first.click()
                    await self._page.wait_for_timeout(3000)
                    print(f"[WeChat] Clicked '{text}'")
                    break
            except Exception:
                continue

        import time
        deadline = time.time() + 120
        while time.time() < deadline:
            token = self._extract_token()
            if token:
                break
            await self._page.wait_for_timeout(1000)
        if not token:
            raise RuntimeError("Login timeout (120s)")
        await self._page.wait_for_timeout(2000)
        print("[WeChat] QR scan successful")

        await self._persist_session()
        print(f"[WeChat] Login OK, token={token}")
        return token

    async def _persist_session(self):
        """Save browser state for next session (per-channel)."""
        os.makedirs(os.path.dirname(self.cookie_path), exist_ok=True)
        try:
            state = await self._context.storage_state()
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception:
            pass
        try:
            cookies = await self._context.cookies()
            with open(self.cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False)
        except Exception:
            pass

    def _extract_token(self) -> str:
        url = self._page.url
        m = re.search(r"[?&]token=(\d+)", url)
        if m:
            return m.group(1)
        return ""

    # ── Debug ────────────────────────────────────────────────

    async def _dump_page(self, label: str):
        html = await self._page.content()
        dump_dir = str(DATA_DIR / "wechat_debug")
        os.makedirs(dump_dir, exist_ok=True)
        path = os.path.join(dump_dir, f"{label}_{datetime.now().strftime('%H%M%S')}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        url = self._page.url[:120]
        print(f"[Debug] {label} URL: {url}")
        print(f"[Debug] HTML saved: {path}")

    # ── Regular article publish ───────────────────────────────

    async def publish(self, article: Article) -> str:
        token = await self.ensure_login()
        cover_file = self._resolve_cover_image(article)

        import time
        editor_url = (
            f"{self.MP_URL}/cgi-bin/appmsg"
            f"?action=edit&type=77&isNew=1&token={token}&lang=zh_CN"
            f"&timestamp={int(time.time() * 1000)}"
        )
        print("[WeChat] Opening editor...")
        await self._page.goto(editor_url, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(5000)
        await self._dump_page("editor")

        return await self._upload_and_save(article, cover_file)

    # ── Sticker publish ──────────────────────────────────────

    async def publish_sticker(self, article: Article) -> str:
        token = await self.ensure_login()

        import time
        editor_url = (
            f"{self.MP_URL}/cgi-bin/appmsg"
            f"?t=media/appmsg_edit_v2&action=edit&isNew=1"
            f"&type=77&createType=8&token={token}&lang=zh_CN"
            f"&timestamp={int(time.time() * 1000)}"
        )
        print("[WeChat] Opening sticker editor...")
        await self._page.goto(editor_url, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(5000)
        await self._dump_page("sticker_editor")

        page_url = self._page.url
        if "createType=8" not in page_url and "appmsg" not in page_url:
            print("[WeChat] Direct URL failed, navigating via UI...")
            await self._page.goto(f"{self.MP_URL}/cgi-bin/appmsg?token={token}&lang=zh_CN", wait_until="domcontentloaded")
            await self._page.wait_for_timeout(3000)
            await self._page.evaluate("""() => {
                const els = document.querySelectorAll('a, button, span, [role=button], div');
                for (const el of els) {
                    const txt = (el.textContent || '').replace(/\\s+/g, '');
                    if (txt.includes('新的创作')) { el.click(); return; }
                }
            }""")
            await self._page.wait_for_timeout(2000)
            await self._page.evaluate("""() => {
                const els = document.querySelectorAll('a, button, span, [role=button], div.weui-desktop-dropdown__list-item');
                for (const el of els) {
                    const txt = (el.textContent || '').replace(/\\s+/g, '');
                    if (txt.includes('贴图')) { el.click(); return; }
                }
            }""")
            await self._page.wait_for_timeout(5000)
            await self._dump_page("sticker_editor_ui")

        # Upload sticker images — resolve all paths first
        sticker_paths: list[str] = []
        if article.wechat_images:
            for img_url in article.wechat_images.split(","):
                local_path = self._resolve_image_path(img_url)
                if local_path and os.path.exists(local_path):
                    sticker_paths.append(local_path)
                else:
                    print(f"[WeChat] Sticker image not found: {local_path}")
        if not sticker_paths:
            raise RuntimeError("没有找到贴图图片文件")
        await self._sticker_upload_all(sticker_paths)

        # Fill title (max 20 chars, sticker editor uses contenteditable div)
        sticker_title = (article.viral_title or article.title or "贴图")[:20]
        await self._fill_sticker_title(sticker_title)

        # Fill description (sticker body text)
        sticker_text = article.sticker_content
        if not sticker_text and article.content:
            import re as _re
            plain = _re.sub(r"<[^>]+>", "", article.content)
            plain = _re.sub(r"\s+", " ", plain).strip()
            sticker_text = plain
        if sticker_text:
            await self._fill_sticker_description(sticker_text)

        # Handle reward setting
        await self._handle_reward()

        # Save draft
        return await self._save_draft(article)

    async def _sticker_upload_all(self, filepaths: list[str]):
        """Upload all sticker images via native file chooser.

        The file input has ``multiple="multiple"``, so we set ALL files at once.
        Success is verified by intercepting the upload API response rather than
        unreliable DOM selectors.
        """
        count = len(filepaths)
        print(f"[WeChat]  Uploading {count} sticker images in batch...")

        # ── Network response + request monitor ─────────────────
        upload_responses: list[dict] = []
        upload_requests: list[dict] = []

        async def _on_response(response):
            url = response.url
            if "filetransfer" in url or ("cgi-bin/appmsg" in url and ("upload" in url or "media" in url)):
                try:
                    body = await response.json()
                    upload_responses.append(body)
                    content = body.get("content") or body.get("media_id") or ""
                    print(f"    [NET] Upload success: url={url[-80:]} content={content}")
                except Exception:
                    pass

        async def _on_request(request):
            url = request.url
            if "filetransfer" in url or ("cgi-bin/appmsg" in url and ("upload" in url or "media" in url)):
                print(f"    [REQ] Upload request: url={url[-80:]}")

        self._page.on("response", _on_response)
        self._page.on("request", _on_request)

        async def _check_wechat_error() -> str | None:
            for sel in [".weui-desktop-toast", ".js_msg_error",
                        ".msg_tips", ".msg_error", ".weui-toast"]:
                els = await self._page.query_selector_all(sel)
                for el in els:
                    if await el.is_visible():
                        txt = (await el.text_content() or "").strip()
                        if txt:
                            return txt
            return None

        # Open popup so WebUploader is in the right state
        popup_open = False
        for i in range(await self._page.locator("a.pop-opr__button").count()):
            btn = self._page.locator("a.pop-opr__button").nth(i)
            if await btn.is_visible():
                popup_open = True
                break
        if not popup_open:
            area = await self._page.query_selector(".image-selector__add")
            if area and await area.is_visible():
                await area.click()
                await self._page.wait_for_timeout(800)

        # 2. Find the file input inside the sticker image selector
        file_input = await self._page.query_selector(
            ".image-selector__add input[type='file']"
        )
        if not file_input:
            file_input = await self._page.query_selector(
                ".image-selector input[type='file']"
            )
        if not file_input:
            file_input = await self._page.query_selector(
                "input[type='file'][multiple]"
            )
        if not file_input:
            raise RuntimeError("找不到贴图文件上传输入框")

        # 3. Set files — WebUploader catches the change and uploads
        await file_input.set_input_files(filepaths)
        print(f"[WeChat]  Files set on input, waiting for upload...")

        # 4. Wait for upload responses
        deadline = 40.0
        waited = 0.0
        while waited < deadline:
            if len(upload_responses) >= count:
                break
            await self._page.wait_for_timeout(2000)
            waited += 2.0

        err = await _check_wechat_error()
        if err and ("空文件" in err or "失败" in err):
            # Uploads triggered but not linked — try to extract media IDs
            # from responses and inject into editor via JS
            print(f"[WeChat]  WeChat error: {err}")

        if len(upload_responses) == 0:
            raise RuntimeError(f"贴图图片上传失败（共 {count} 张），无上传响应")

        media_ids = []
        for r in upload_responses:
            mid = r.get("content") or r.get("media_id") or ""
            if mid:
                media_ids.append(mid)

        print(f"[WeChat]  Got {len(media_ids)} media IDs: {media_ids}")

        # Give WebUploader time to link uploaded files into the editor state
        await self._page.wait_for_timeout(3000)
        err = await _check_wechat_error()
        if err and ("空文件" in err or "失败" in err):
            raise RuntimeError(f"微信上传失败: {err}")
        print(f"[WeChat]  All {count} images uploaded and linked to editor")
        return

    # ── Title / Description (sticker) ────────────────────────

    async def _fill_sticker_title(self, text: str):
        text = text[:20]
        title_locator = self._page.locator("#js_title_main div").nth(3)
        try:
            if await title_locator.count() > 0:
                await title_locator.click()
                await self._page.wait_for_timeout(300)
                await title_locator.fill("")
                await title_locator.fill(text)
                print(f"[WeChat] Title filled via #js_title_main div:nth(3) ({len(text)} chars)")
                return
        except Exception:
            pass
        # Fallback: hidden #title input
        try:
            title_input = await self._page.wait_for_selector("#title", state="attached", timeout=3000)
            if title_input:
                await title_input.fill(text)
                print(f"[WeChat] Title filled via #title")
                return
        except Exception:
            pass
        # Final fallback
        filled = await self._page.evaluate(f"""() => {{
            const el = document.querySelector('#js_title_main div[contenteditable], #title, .js_title');
            if (el) {{
                el.focus();
                el.innerText = {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }}""")
        if filled:
            print(f"[WeChat] Title filled via evaluate ({len(text)} chars)")
        else:
            print("[WeChat]  Could not find title field")

    async def _fill_sticker_description(self, text: str):
        print(f"[WeChat] Sticker description ({len(text)} chars)")
        # Placeholder text "填写描述信息" (Codegen confirmed)
        try:
            desc_div = self._page.locator("div").filter(has_text=re.compile(r"填写描述信息")).first
            if await desc_div.count() > 0:
                await desc_div.click()
                await self._page.wait_for_timeout(300)
                await desc_div.fill(text)
                print(f"[WeChat] Description filled via placeholder text")
                return
        except Exception:
            pass
        for sel in ["#js_description", ".rich_media_content", ".js_appmsg_desc",
                    "textarea[name='description']", ".appmsg_description"]:
            try:
                el = await self._page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    await self._page.wait_for_timeout(300)
                    await el.fill(text)
                    print(f"[WeChat] Description filled via '{sel}'")
                    return
            except Exception:
                continue
        filled = await self._page.evaluate(f"""() => {{
            const edits = document.querySelectorAll('[contenteditable=true], textarea, .rich_media_content');
            for (const el of edits) {{
                if (el.offsetParent === null) continue;
                if (el.closest('#js_title_main, .js_title, #title')) continue;
                el.focus();
                el.innerText = {json.dumps(text)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }}""")
        if filled:
            print(f"[WeChat] Description filled via evaluate")
        else:
            print("[WeChat]  WARNING: could not find description field")

    async def _handle_reward(self):
        """Enable reward (赞赏) if currently OFF."""
        await self._page.wait_for_timeout(500)
        reward_area = await self._page.query_selector("#js_reward_setting_area")
        if reward_area:
            no_open_text = await reward_area.query_selector("text=不开启")
            if no_open_text:
                print("[WeChat] Reward is OFF, enabling...")
                try:
                    await no_open_text.click()
                    await self._page.wait_for_timeout(800)
                    confirm_btn = self._page.get_by_role("button", name="确定")
                    if await confirm_btn.is_visible():
                        await confirm_btn.click()
                        await self._page.wait_for_timeout(500)
                        print("[WeChat] Reward enabled")
                except Exception:
                    pass
            else:
                print("[WeChat] Reward already ON")

    # ── Regular editor helpers ───────────────────────────────

    def _resolve_image_path(self, img_url: str) -> str | None:
        path = (img_url or "").strip()
        if not path:
            return None
        if os.path.exists(path):
            return path
        rel = path.replace("/data/wechat/", "").replace("\\", "/")
        full = str(DATA_DIR / "wechat" / rel)
        if os.path.exists(full):
            return full
        rel2 = path.replace("/data/images/", "").replace("\\", "/")
        full2 = str(DATA_DIR / "images" / rel2)
        if os.path.exists(full2):
            return full2
        return None

    async def _upload_and_save(self, article: Article, cover_file: str | None) -> str:
        await self._dump_page("editor")

        if article.content:
            await self._write_body_text(article.content)
        else:
            print("[WeChat]  No article content")

        title_text = article.title or "AI 热点速递"
        await self._fill_title(title_text)

        if cover_file and os.path.exists(cover_file):
            await self._upload_one_image(cover_file, 1, 1)
            await self._set_cover_from_content()
        else:
            print("[WeChat]  No cover image found, skipping cover")

        if article.sticker_content:
            await self._fill_description(article.sticker_content)
        else:
            print("[WeChat]  No sticker content, skipping description")

        return await self._save_draft(article)

    async def _write_body_text(self, html_text: str):
        print(f"[WeChat] Writing body text ({len(html_text)} chars)...")
        # Find ProseMirror that is NOT inside the title area
        found = await self._page.evaluate("""() => {
            const all = document.querySelectorAll('.ProseMirror');
            for (const pm of all) {
                if (!pm.closest('#js_title_main') && pm.offsetParent !== null) {
                    return true;  // found the body editor
                }
            }
            return false;
        }""")
        if not found:
            print("[WeChat]  Could not find body ProseMirror (not inside title area)")
            await self._dump_page("no_pm_editor")
            return
        # Click and write to the body ProseMirror
        await self._page.evaluate(f"""() => {{
            const all = document.querySelectorAll('.ProseMirror');
            for (const pm of all) {{
                if (!pm.closest('#js_title_main') && pm.offsetParent !== null) {{
                    pm.focus();
                    document.execCommand('selectAll');
                    document.execCommand('delete');
                    document.execCommand('insertHTML', false, {json.dumps(html_text)});
                    return true;
                }}
            }}
            return false;
        }}""")
        await self._page.wait_for_timeout(1000)
        print("[WeChat] Body text written")

    async def _fill_title(self, text: str):
        text = text[:64]
        # Codegen confirmed: this is the title in WeChat's new editor
        title_locator = self._page.locator("#js_title_main div").nth(3)
        try:
            if await title_locator.count() > 0:
                await title_locator.click()
                await self._page.wait_for_timeout(200)
                await title_locator.fill(text)
                print(f"[WeChat] Title filled via #js_title_main div:nth(3) ({len(text)} chars)")
                return
        except Exception:
            pass
        # Legacy fallback
        try:
            title_el = await self._page.wait_for_selector("#title", state="attached", timeout=3000)
            if title_el:
                await title_el.click()
                await title_el.fill(text)
                print(f"[WeChat] Title filled via #title")
                return
        except Exception:
            pass
        filled = await self._page.evaluate(f"""() => {{
            const el = document.querySelector('#js_title_main div[contenteditable], #title, .js_title');
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
            print(f"[WeChat] Title filled via evaluate")
        else:
            print("[WeChat]  Could not find title field")

    async def _set_cover_from_content(self):
        print("[WeChat] Setting cover from first content image...")
        cover_btn = await self._page.query_selector("#js_cover_area .js_cover_btn_area")
        if cover_btn:
            await cover_btn.click()
            await self._page.wait_for_timeout(500)

        await self._page.evaluate("""() => {
            const el = document.querySelector('a.js_selectCoverFromContent');
            if (el) el.click();
        }""")
        await self._page.wait_for_timeout(1000)

        clicked = await self._page.evaluate("""() => {
            const item = document.querySelector('li.appmsg_content_img_item');
            if (!item) return false;
            item.click();
            return true;
        }""")
        if not clicked:
            print("[WeChat]  No images in content, skipping cover")
            return
        print("[WeChat] Selected first image")
        await self._page.wait_for_timeout(500)

        await self._page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if ((b.textContent || '').trim() === '下一步') b.click();
            }
        }""")
        await self._page.wait_for_timeout(1500)

        await self._page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = (b.textContent || '').trim();
                if (t.includes('确认')) { b.click(); return; }
            }
        }""")
        print("[WeChat] Cover set")
        await self._page.wait_for_timeout(1500)

    def _resolve_cover_image(self, article: Article) -> str | None:
        path = (article.cover_image or "").strip()
        if not path:
            return None
        rel = path.replace("/data/images/", "").replace("\\", "/")
        full = str(DATA_DIR / "images" / rel)
        if os.path.exists(full):
            return full
        if os.path.exists(path):
            return path
        return None

    async def _upload_one_image(self, filepath: str, idx: int, total: int):
        print(f"[WeChat]  Uploading {idx}/{total}: {os.path.basename(filepath)}")
        file_input = await self._page.query_selector("input[type='file']")
        if file_input:
            await file_input.set_input_files(filepath)
        else:
            await self._page.evaluate("""() => {
                const el = document.createElement('input');
                el.type = 'file';
                el.id = '__pw_uploader__';
                el.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;opacity:0;pointer-events:none;width:1px;height:1px';
                el.multiple = false;
                el.accept = 'image/*';
                document.body.appendChild(el);
            }""")
            file_input = await self._page.wait_for_selector("#__pw_uploader__", timeout=3000)
            if file_input:
                await file_input.set_input_files(filepath)
                await self._page.evaluate("""() => {
                    const el = document.getElementById('__pw_uploader__');
                    if (el) el.dispatchEvent(new Event('change', {bubbles: true}));
                }""")
            await self._try_click_upload_button()

        await self._page.wait_for_timeout(5000)
        try:
            await self._page.wait_for_selector(
                "img[src*='mmbiz'], img[src*='tmp'], .upload-preview img, .js_img_prev img",
                timeout=30000,
            )
            print(f"[WeChat]  Upload {idx}/{total} done")
        except Exception:
            print(f"[WeChat]  Upload {idx}/{total} - waiting additional time")
            await self._page.wait_for_timeout(10000)

    async def _try_click_upload_button(self):
        selectors = [
            ".upload_image_area", ".js_upload_image_area", ".appmsg_upload_img",
            ".js_file_upload", "[data-role='uploader']",
            "a:has-text('上传')", "a:has-text('添加图片')", "a:has-text('选择图片')",
            "div[class*='upload']", "a[class*='upload']", "span[class*='upload']",
        ]
        for sel in selectors:
            try:
                el = await self._page.wait_for_selector(sel, timeout=2000)
                if el and await el.is_visible():
                    await el.click()
                    await self._page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    async def _fill_description(self, text: str):
        text = text[:120]
        print(f"[WeChat] Description ({len(text)} chars)")
        selectors = [
            "#js_description", "textarea[name='description']",
            ".appmsg_description", ".rich_media_content", ".js_appmsg_desc",
            "div[contenteditable='true']", "div[class*='editor']",
            "div[class*='content']", ".rich_media_area_primary", "textarea",
        ]
        for sel in selectors:
            try:
                el = await self._page.wait_for_selector(sel, timeout=2000)
                if el and await el.is_visible():
                    await el.click()
                    await el.fill(text)
                    print(f"[WeChat] Description filled via '{sel}' ({len(text)} chars)")
                    return
            except Exception:
                continue
        filled = await self._page.evaluate(f"""() => {{
            const edits = document.querySelectorAll('[contenteditable=true], .rich_media_content, .rich_media_area_primary');
            for (const el of edits) {{
                if (el.offsetParent !== null) {{
                    el.focus();
                    el.innerText = {json.dumps(text)};
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            }}
            return false;
        }}""")
        if filled:
            print(f"[WeChat] Description filled via evaluate() ({len(text)} chars)")
        else:
            print("[WeChat]  WARNING: could not find description field")
            await self._dump_page("no_desc_field")

    async def _save_draft(self, article: Article) -> str:
        await self._page.wait_for_timeout(2000)

        save_selectors = [
            "#js_submit button", "#js_save_btn",
            "button:has-text('保存为草稿')",
            "button.weui-desktop-btn_primary:not(.weui-desktop-btn_disabled)",
            "a:has-text('提交保存')",
        ]
        saved = False
        for sel in save_selectors:
            try:
                btn = await self._page.wait_for_selector(sel, timeout=3000)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    saved = True
                    print(f"[WeChat] Clicked save: '{sel}'")
                    break
            except Exception:
                continue

        if not saved:
            try:
                save_btn = self._page.get_by_role("button", name="保存为草稿")
                if await save_btn.is_visible():
                    await save_btn.click()
                    saved = True
                    print("[WeChat] Clicked save via role button")
            except Exception:
                pass

        if not saved:
            print("[WeChat]  Could not find save button")
            await self._dump_page("no_save_btn")
            return ""

        await self._page.wait_for_timeout(3000)

        draft_id = ""
        for _ in range(20):
            current_url = self._page.url
            m = re.search(r"appmsgid=(\d+)", current_url)
            if m:
                draft_id = m.group(1)
                break
            success_visible = await self._page.evaluate("""() => {
                const el = document.querySelector('#js_save_success');
                return el && el.style.display !== 'none' ? true : false;
            }""")
            if success_visible:
                print("[WeChat] Save success message visible")
                draft_id = await self._page.evaluate(r"""() => {
                    const html = document.body.innerHTML;
                    const m = html.match(/appmsgid[=:][^"']*?(\d{8,15})/);
                    return m ? m[1] : '';
                }""")
                if draft_id:
                    break
            await self._page.wait_for_timeout(1000)

        if draft_id:
            token = self._extract_token()
            preview_url = (
                f"{self.MP_URL}/cgi-bin/appmsg"
                f"?token={token}&lang=zh_CN"
                f"&type=77&action=edit&appmsgid={draft_id}"
            )
            print(f"[WeChat] Draft saved: {preview_url}")
            return preview_url
        else:
            print(f"[WeChat] After save URL: {self._page.url[:100]}...")
            return self._page.url


# ── Standalone helpers ───────────────────────────────────────

async def wechat_login(channel_id: int = 0):
    async with WeChatPublisher(channel_id=channel_id) as pub:
        await pub.ensure_login()
    print(f"[WeChat] Login completed for channel {channel_id}, cookie saved")


async def wechat_upload(article: Article, channel_id: int = 0, headless: bool = False) -> str:
    async with WeChatPublisher(channel_id=channel_id, headless=headless) as pub:
        return await pub.publish(article)


async def wechat_status(channel_id: int = 0) -> bool:
    pub = WeChatPublisher(channel_id=channel_id)
    if not os.path.exists(pub.cookie_path):
        print(f"[WeChat] No saved cookie for channel {channel_id} - run `wechat login` first")
        return False

    async with WeChatPublisher(channel_id=channel_id) as pub:
        try:
            await pub.ensure_login()
            print(f"[WeChat] Cookie valid, logged in (channel {channel_id})")
            return True
        except Exception as e:
            print(f"[WeChat] Login failed for channel {channel_id}: {e}")
            return False
