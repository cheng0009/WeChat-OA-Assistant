"""WechatSogou source plugin - fetches articles from Sogou WeChat search."""
import re
import random
from datetime import datetime
import httpx
from .base import BaseSource, normalize_item

SOGOU_SEARCH_URL = "https://weixin.sogou.com/weixin"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://weixin.sogou.com/",
    "Connection": "keep-alive",
}


class WechatSogouSource(BaseSource):
    type_id = "wechat_sogou"
    label = "微信搜狗"

    def __init__(self, api_url="", api_key="", config=None):
        super().__init__(api_url, api_key, config)
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": UA, **EXTRA_HEADERS})
        self.keywords = self.config.get("keywords", [])
        self.wechat_accounts = self.config.get("wechat_accounts", [])
        self.max_items = int(self.config.get("max_items", 20))
        self.proxy = self.config.get("proxy", "")

    async def _search_by_keyword(self, kw: str) -> list[dict]:
        """Search Sogou WeChat by keyword, parse results directly."""
        params = {"type": 2, "query": kw}
        resp = await self._http.get(SOGOU_SEARCH_URL, params=params)
        resp.raise_for_status()
        html = resp.text
        # Captcha / anti-spider detection
        if "antispider" in str(resp.url) or len(html) < 8000:
            print(f"[WechatSogou] ⚠️ 搜狗返回反爬页面（{resp.url}），关键词 '{kw}' 抓取跳过")
            return []
        items = []

        # Find each result block: <li> inside <ul class="news-list">
        for li_html in re.findall(r'<li[^>]*id="sogou_vr[^"]*"[^>]*>.*?</li>\s*(?:<!--\s*[z]\s*-->)?', html, re.DOTALL):
            # Title
            title_m = re.search(r'<h3>\s*<a[^>]*>(.*?)</a>\s*</h3>', li_html, re.DOTALL)
            title = ""
            if title_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                title = title.replace("red_beg", "").replace("red_end", "").replace("<!--", "").replace("-->", "").strip()

            # Sogou link URL
            url_m = re.search(r'<a[^>]*href="(/link\?url=[^"]+)"', li_html)
            url = ""
            if url_m:
                url = "https://weixin.sogou.com" + url_m.group(1)

            # Summary
            summary_m = re.search(r'<p[^>]*class="txt-info"[^>]*>(.*?)</p>', li_html, re.DOTALL)
            summary = ""
            if summary_m:
                summary = re.sub(r'<[^>]+>', '', summary_m.group(1)).strip()
                summary = summary.replace("red_beg", "").replace("red_end", "").replace("<!--", "").replace("-->", "").strip()

            # Account name
            account_m = re.search(r'<span[^>]*class="all-time-y2"[^>]*>(.*?)</span>', li_html)
            account = account_m.group(1).strip() if account_m else ""

            # Timestamp
            time_m = re.search(r"timeConvert\('(\d+)'\)", li_html)
            pub_str = ""
            if time_m:
                pub_ts = int(time_m.group(1))
                pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M")

            if title and url:
                items.append({
                    "title": title,
                    "url": url,
                    "source": account,
                    "summary": summary,
                    "account": account,
                    "publishedAt": pub_str,
                })

        return items

    async def fetch(self) -> list[dict]:
        results = []
        seen_urls = set()
        max_items = self.max_items
        keywords = list(self.keywords)
        accounts = list(self.wechat_accounts)
        random.shuffle(keywords)
        random.shuffle(accounts)

        # ── Pass 1: 指定公众号 + 关键词匹配 ──────────────────
        if keywords and accounts:
            for acc in accounts:
                if len(results) >= max_items:
                    break
                try:
                    articles = await self._fetch_by_account(acc)
                    for art in articles:
                        if len(results) >= max_items:
                            break
                        title = (art.get("title") or "")
                        if not any(kw.lower() in title.lower() for kw in keywords):
                            continue
                        item_url, full_content = await self._fetch_article_content(art.get("url", ""))
                        if not item_url:
                            item_url = art.get("url", "")
                        if not item_url or item_url in seen_urls:
                            continue
                        seen_urls.add(item_url)
                        results.append(normalize_item({
                            "title": title,
                            "url": item_url,
                            "source": acc,
                            "summary": art.get("summary", ""),
                            "content": full_content,
                            "category": "wechat",
                            "publishedAt": art.get("publishedAt", ""),
                        }, default_source=acc))
                except Exception as e:
                    print(f"[WechatSogou] Account '{acc}' fetch error: {e}")

            if not results:
                print(f"[WechatSogou] 指定公众号未匹配到含关键词的文章，降级为全局关键词搜索")

        # ── Pass 2: 纯关键词搜索（降级 / 仅配关键词） ─────────
        if keywords and (not accounts or not results):
            per_keyword = max(1, max_items // len(keywords))
            extra = max_items - per_keyword * len(keywords)
            for i, kw in enumerate(keywords):
                if len(results) >= max_items:
                    break
                budget = per_keyword + (1 if i < extra else 0)
                try:
                    articles = await self._search_by_keyword(kw)
                    kw_count = 0
                    for art in articles:
                        if len(results) >= max_items or kw_count >= budget:
                            break
                        item_url, full_content = await self._fetch_article_content(art.get("url", ""))
                        if not item_url:
                            item_url = art.get("url", "")
                        if not item_url or item_url in seen_urls:
                            continue
                        seen_urls.add(item_url)
                        results.append(normalize_item({
                            "title": art.get("title", ""),
                            "url": item_url,
                            "source": art.get("account", ""),
                            "summary": art.get("summary", ""),
                            "content": full_content,
                            "category": "wechat",
                            "publishedAt": art.get("publishedAt", ""),
                        }, default_source=art.get("account", "") or "微信搜狗"))
                        kw_count += 1
                except Exception as e:
                    print(f"[WechatSogou] Keyword '{kw}' search error: {e}")

        # ── Pass 3: 只有公众号 ─────────────────────────────
        if accounts and not keywords:
            for acc in accounts:
                if len(results) >= max_items:
                    break
                try:
                    articles = await self._fetch_by_account(acc)
                    for art in articles:
                        if len(results) >= max_items:
                            break
                        item_url, full_content = await self._fetch_article_content(art.get("url", ""))
                        if not item_url:
                            item_url = art.get("url", "")
                        if not item_url or item_url in seen_urls:
                            continue
                        seen_urls.add(item_url)
                        results.append(normalize_item({
                            "title": art.get("title", ""),
                            "url": item_url,
                            "source": acc,
                            "summary": art.get("summary", ""),
                            "content": full_content,
                            "category": "wechat",
                            "publishedAt": art.get("publishedAt", ""),
                        }, default_source=acc))
                except Exception as e:
                    print(f"[WechatSogou] Account '{acc}' fetch error: {e}")

        final = results[:max_items]
        if len(final) < 3:
            print(f"[WechatSogou] ⚠️ 仅抓取到 {len(final)} 篇，建议在频道中添加更多关键词或公众号")
        return self._apply_keywords(final)

    async def _fetch_by_account(self, acc: str) -> list[dict]:
        """Fetch articles by account name via wechatsogou library."""
        try:
            import wechatsogou
            kwargs = {}
            if self.proxy:
                kwargs["proxy"] = self.proxy
            ws_api = wechatsogou.WechatSogouAPI(**kwargs)
            history = ws_api.get_gzh_article_by_history(acc)
            articles_raw = history.get("article", []) if isinstance(history, dict) else []
            items = []
            for art in articles_raw:
                items.append({
                    "title": art.get("title", ""),
                    "url": art.get("content_url", ""),
                    "summary": art.get("abstract", ""),
                    "publishedAt": "",
                })
                pub_ts = art.get("datetime", 0)
                if pub_ts:
                    try:
                        items[-1]["publishedAt"] = datetime.fromtimestamp(int(pub_ts)).strftime("%Y-%m-%d %H:%M")
                    except (ValueError, OSError):
                        pass
            return items
        except ImportError:
            print("[WechatSogou] wechatsogou library not installed, skipping account search")
            return []

    async def _fetch_article_content(self, url: str) -> tuple[str, str]:
        """Fetch article, follow redirects, return (resolved_url, content_text).

        The resolved URL is the real mp.weixin.qq.com URL (stable for dedup),
        not the temporary Sogou redirect URL.
        """
        if not url:
            return ("", "")
        try:
            resp = await self._http.get(url, timeout=15)
            resp.raise_for_status()
            resolved = str(resp.url)
            html = resp.text
            # Captcha check on article fetch
            if "antispider" in resolved or len(html) < 2000:
                return ("", "")
            m = re.search(r'id="rich_media_content"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
            if m:
                text = re.sub(r'<[^>]+>', '', m.group(1))
                text = re.sub(r'\s+', ' ', text).strip()
                return (resolved, text[:3000])
            m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
            if m:
                text = re.sub(r'<[^>]+>', '', m.group(1))
                text = re.sub(r'\s+', ' ', text).strip()
                return (resolved, text[:3000])
            return (resolved, "")
        except Exception:
            return ("", "")

    async def test(self) -> str:
        kw = self.keywords[0] if self.keywords else "AI"
        try:
            articles = await self._search_by_keyword(kw)
            return f"OK, found {len(articles)} articles for keyword '{kw}'"
        except httpx.HTTPStatusError as e:
            return f"搜狗返回 {e.response.status_code}，可能被反爬限制"
        except httpx.RequestError as e:
            return f"网络请求失败: {e}"
        except Exception as e:
            return f"搜索失败: {type(e).__name__}: {e}"

    async def close(self):
        await self._http.aclose()
