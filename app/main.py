import os, json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from pathlib import Path

from app.database import init_db, get_db
from app.models import Article, NewsItem, DailyLog, Source, Channel
from app.config import settings, BASE_DIR, ARTICLES_DIR, IMAGES_DIR, WECHAT_IMAGES_DIR, CHANNEL_UPLOADS_DIR
from app.scheduler import start_scheduler, stop_scheduler, daily_job
from app.fetcher import test_source
from app.generator import DeepSeekGenerator, SYSTEM_PROMPT_FULL
from app.image_gen import generate_cover_image
from app.sources import list_source_types, get_source_class
from app.wechat_image_gen import generate_wechat_images, STYLES

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["from_json"] = lambda v: json.loads(v) if v and isinstance(v, str) else {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="AI HOT 公众号助手", lifespan=lifespan)

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

data_images = IMAGES_DIR
data_images.mkdir(parents=True, exist_ok=True)
app.mount("/data/images", StaticFiles(directory=str(data_images)), name="images")

data_wechat = WECHAT_IMAGES_DIR
data_wechat.mkdir(parents=True, exist_ok=True)
app.mount("/data/wechat", StaticFiles(directory=str(data_wechat)), name="wechat")

channel_uploads = CHANNEL_UPLOADS_DIR
channel_uploads.mkdir(parents=True, exist_ok=True)
app.mount("/data/channel_uploads", StaticFiles(directory=str(channel_uploads)), name="channel_uploads")


# ─── Channel context helper ───────────────────────────────────────

async def get_channels(db: AsyncSession) -> list[Channel]:
    result = await db.execute(select(Channel).order_by(Channel.id))
    return result.scalars().all()


async def resolve_channel(db: AsyncSession, channel_id: int | None = None) -> Channel | None:
    if channel_id:
        result = await db.execute(select(Channel).where(Channel.id == channel_id))
        return result.scalar_one_or_none()
    result = await db.execute(select(Channel).order_by(Channel.id).limit(1))
    return result.scalar_one_or_none()


def channel_redirect(path: str, channel_id: int | None = None) -> RedirectResponse:
    if channel_id:
        url = f"{path}?c={channel_id}"
    else:
        url = path
    return RedirectResponse(url=url, status_code=302)


# ─── Dashboard ───────────────────────────────────────────────────

@app.get("/")
async def index(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    channels = await get_channels(db)
    if not channels:
        return RedirectResponse(url="/channels", status_code=302)
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    base_where = [Article.channel_id == cid] if cid else []

    result = await db.execute(select(func.count(Article.id)).where(*base_where))
    total_articles = result.scalar() or 0

    result = await db.execute(
        select(func.count(Article.id)).where(Article.status == "published", *base_where)
    )
    published = result.scalar() or 0

    result = await db.execute(
        select(func.count(Article.id)).where(Article.status == "draft", *base_where)
    )
    drafts = result.scalar() or 0

    result = await db.execute(select(func.count(NewsItem.id)))
    total_items = result.scalar() or 0

    result = await db.execute(
        select(Article).where(*base_where).order_by(desc(Article.created_at)).limit(5)
    )
    recent_articles = result.scalars().all()

    # Source count for current channel
    source_where = [Source.channel_id == cid] if cid else []
    result = await db.execute(select(func.count(Source.id)).where(*source_where))
    source_count = result.scalar() or 0

    # Pending rewrite count
    pending_rewrite = 0
    if current:
        result = await db.execute(
            select(func.count(NewsItem.id))
            .where(NewsItem.channel_id == cid, NewsItem.article_id == None)
        )
        pending_rewrite = result.scalar() or 0

    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "channels": channels,
        "current_channel": current,
        "stats": {
            "total_articles": total_articles,
            "published": published,
            "drafts": drafts,
            "total_items": total_items,
            "pending_rewrite": pending_rewrite,
            "scheduler_running": True,  # cron loop runs as long as server is up
            "schedule_hour": current.schedule_hour if current else settings.schedule_hour,
            "schedule_minute": current.schedule_minute if current else settings.schedule_minute,
            "schedule_enabled": current.schedule_enabled if current else False,
            "model": settings.deepseek_model if settings.deepseek_api_key else None,
            "source_count": source_count if current else 0,
            "channel_name": current.name if current else "默认",
        },
        "recent_articles": recent_articles,
    })


# ─── Article management ──────────────────────────────────────────

@app.get("/articles")
async def article_list(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    channels = await get_channels(db)
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    where = [Article.channel_id == cid] if cid else []
    result = await db.execute(
        select(Article).where(*where).order_by(desc(Article.created_at)).limit(50)
    )
    articles = result.scalars().all()
    return templates.TemplateResponse(request, "articles.html", {
        "request": request,
        "channels": channels,
        "current_channel": current,
        "articles": articles,
    })


@app.get("/articles/{article_id}")
async def article_detail(article_id: int, request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    channels = await get_channels(db)
    current = await resolve_channel(db, c)

    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        return channel_redirect("/articles", current.id if current else None)

    result = await db.execute(
        select(NewsItem).where(NewsItem.article_id == article_id)
    )
    news_items = result.scalars().all()

    return templates.TemplateResponse(request, "article_detail.html", {
        "request": request,
        "channels": channels,
        "current_channel": current,
        "article": article,
        "news_items": news_items,
        "styles": STYLES,
    })


@app.post("/articles/{article_id}/publish")
async def publish_article(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article:
        article.status = "published"
        await db.commit()
    return channel_redirect(f"/articles/{article_id}", c)


@app.post("/articles/{article_id}/set-style")
async def set_article_style(article_id: int, request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        return channel_redirect("/articles", c)

    form = await request.form()
    style_name = form.get("style", "deep_blue")
    if style_name not in STYLES:
        style_name = "deep_blue"

    article.image_style = style_name

    if article.sticker_content and article.viral_title:
        try:
            # Load channel for per-channel avatar/qrcode
            ch = None
            if article.channel_id:
                ch_result = await db.execute(select(Channel).where(Channel.id == article.channel_id))
                ch = ch_result.scalar_one_or_none()
            files = await generate_wechat_images(
                article.title, article.viral_title,
                article.sticker_content, article.source_date or "",
                style_name=style_name,
                avatar_path=ch.avatar_image if ch else None,
                qrcode_path=ch.qrcode_image if ch else None,
                date_prefix=ch.name if ch else None,
            )
            article.wechat_images = ",".join(files)
        except Exception as e:
            print(f"[Style] Regeneration error: {e}")
            import traceback
            traceback.print_exc()

    await db.commit()
    return channel_redirect(f"/articles/{article_id}", c)


@app.post("/articles/{article_id}/delete")
async def delete_article(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article:
        await db.delete(article)
        await db.commit()
    return channel_redirect("/articles", c)


@app.post("/articles/{article_id}/regenerate-cover")
async def regenerate_cover(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article:
        ch_result = await db.execute(select(Channel).where(Channel.id == article.channel_id))
        ch = ch_result.scalar_one_or_none()
        source_name = ch.name if ch else "AI HOT"
        cover = await generate_cover_image(article.viral_title or article.title, article.source_date, source_name=source_name)
        article.cover_image = cover
        await db.commit()
    return channel_redirect(f"/articles/{article_id}", c)


@app.post("/articles/{article_id}/export-images")
async def export_wechat_images(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article or not article.wechat_images:
        return channel_redirect(f"/articles/{article_id}", c)

    import shutil
    from datetime import datetime

    export_dir = os.path.join(str(BASE_DIR), "exported_images", f"{article.source_date or datetime.now().strftime('%Y-%m-%d')}-{article.id}")
    os.makedirs(export_dir, exist_ok=True)

    wechat_dir = str(WECHAT_IMAGES_DIR)
    count = 0
    for url_path in article.wechat_images.split(","):
        rel = url_path.replace("/data/wechat/", "").replace("\\", "/")
        src = os.path.join(wechat_dir, rel)
        if os.path.exists(src):
            dst = os.path.join(export_dir, os.path.basename(rel))
            shutil.copy2(src, dst)
            count += 1

    return HTMLResponse(f'''
    <html><body>
    <script>
        alert("已导出 {count} 张图片到：\\n{export_dir}\\n\\n打开此文件夹即可上传到微信贴图。");
        window.location.href = "/articles/{article_id}{'?c=' + str(c) if c else ''}";
    </script>
    </body></html>
    ''')


@app.post("/articles/{article_id}/wechat-upload")
async def wechat_upload(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    from app.wechat_publisher import WeChatPublisher
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        return channel_redirect("/articles", c)

    try:
        ch_id = article.channel_id or c or 0
        async with WeChatPublisher(channel_id=ch_id) as pub:
            draft_url = await pub.publish(article)
        article.wechat_draft_url = draft_url
        await db.commit()
        msg = f"微信贴图草稿已创建！\\n{draft_url}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        msg = f"上传失败: {e}"

    return HTMLResponse(f'''
    <html><body>
    <script>alert({json.dumps(msg)}); window.location.href="/articles/{article_id}{'?c=' + str(c) if c else ''}";</script>
    </body></html>
    ''')


@app.post("/articles/{article_id}/publish-sticker")
async def publish_sticker(article_id: int, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    from app.wechat_publisher import WeChatPublisher
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        return channel_redirect("/articles", c)

    try:
        ch_id = article.channel_id or c or 0
        async with WeChatPublisher(channel_id=ch_id) as pub:
            draft_url = await pub.publish_sticker(article)
        article.wechat_sticker_url = draft_url
        await db.commit()
        msg = f"贴图草稿已创建！\\n{draft_url}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        msg = f"发布贴图失败: {e}"

    return HTMLResponse(f'''
    <html><body>
    <script>alert({json.dumps(msg)}); window.location.href="/articles/{article_id}{'?c=' + str(c) if c else ''}";</script>
    </body></html>
    ''')


# ─── Source management ─────────────────────────────────────────────

# ─── (standalone /sources routes removed — use /channels/{id}/edit instead) ───


# ─── WeChat Rewrite ─────────────────────────────────────────────

@app.get("/wechat-rewrite")
async def wechat_rewrite_list(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    channels = await get_channels(db)
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    # WeChat Sogou sources for this channel
    ws_sources = []
    if cid:
        result = await db.execute(
            select(Source).where(Source.channel_id == cid, Source.source_type == "wechat_sogou")
        )
        ws_sources = result.scalars().all()

    # Pending items (not linked to any article)
    pending = []
    if cid:
        result = await db.execute(
            select(NewsItem)
            .where(NewsItem.channel_id == cid, NewsItem.article_id == None)
            .order_by(desc(NewsItem.created_at))
            .limit(100)
        )
        pending = result.scalars().all()

    # Rewritten items (linked to an article)
    rewritten = []
    if cid:
        result = await db.execute(
            select(NewsItem)
            .where(NewsItem.channel_id == cid, NewsItem.article_id != None)
            .order_by(desc(NewsItem.created_at))
            .limit(100)
        )
        rewritten = result.scalars().all()

    return templates.TemplateResponse(request, "wechat_rewrite.html", {
        "request": request,
        "channels": channels,
        "current_channel": current,
        "ws_sources": ws_sources,
        "pending": pending,
        "rewritten": rewritten,
    })


@app.post("/wechat-rewrite/fetch")
async def wechat_rewrite_fetch(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    """Fetch latest articles from WeChat Sogou sources for current channel."""
    current = await resolve_channel(db, c)
    cid = current.id if current else 0
    if not cid:
        return channel_redirect("/wechat-rewrite", None)

    from app.sources import get_source
    import json

    result = await db.execute(
        select(Source).where(Source.channel_id == cid, Source.source_type == "wechat_sogou", Source.enabled == True)
    )
    sources = result.scalars().all()

    count = 0
    for src_row in sources:
        try:
            config = json.loads(src_row.config) if src_row.config else {}
            instance = get_source("wechat_sogou", api_url=src_row.api_url, api_key=src_row.api_key or "", config=config)
            items = await instance.fetch()
            for item in items:
                # Check dedup by url
                existing = await db.execute(
                    select(NewsItem).where(NewsItem.url == item.get("url", ""), NewsItem.channel_id == cid)
                )
                if existing.scalar_one_or_none():
                    continue
                ni = NewsItem(
                    channel_id=cid,
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=item.get("source", src_row.name),
                    summary=item.get("summary", ""),
                    content=item.get("content", ""),
                    category=item.get("category", "wechat"),
                    published_at=item.get("publishedAt", ""),
                )
                db.add(ni)
                count += 1
            if hasattr(instance, "close"):
                await instance.close()
        except Exception as e:
            print(f"[WechatRewrite] Fetch error for {src_row.name}: {e}")

    await db.commit()
    return HTMLResponse(f'''
    <html><body>
    <script>alert("抓取完成，新增 {count} 条"); window.location.href="/wechat-rewrite?c={cid}";</script>
    </body></html>
    ''')


@app.post("/wechat-rewrite/{item_id}/rewrite")
async def wechat_rewrite_item(item_id: int, request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    """Rewrite a single WeChat article."""
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    result = await db.execute(select(NewsItem).where(NewsItem.id == item_id, NewsItem.channel_id == cid))
    item = result.scalar_one_or_none()
    if not item:
        return channel_redirect("/wechat-rewrite", c)

    from app.comment_rewriter import CommentRewriter
    rewriter = CommentRewriter(channel=current, generator=DeepSeekGenerator())
    article_data = await rewriter.rewrite_item({
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "summary": item.summary,
        "content": item.content,
    })

    if article_data:
        title = article_data.get("title", item.title)
        summary = article_data.get("summary", "")
        content = article_data.get("content", "")

        cover = await generate_cover_image(title, "", source_name=current.name if current else "AI HOT")
        from app.scheduler import _md_to_html
        content_html = _md_to_html(content, title)

        article = Article(
            channel_id=cid,
            title=title,
            content=content_html,
            summary=summary,
            cover_image=cover,
            status="draft",
            is_daily=False,
        )
        db.add(article)
        await db.flush()

        # Link the NewsItem to this article
        item.article_id = article.id
        await db.commit()

        return HTMLResponse(f'''
        <html><body>
        <script>alert("改写完成！"); window.location.href="/articles/{article.id}?c={cid}";</script>
        </body></html>
        ''')

    return HTMLResponse(f'''
    <html><body>
    <script>alert("改写失败（API 问题？）"); window.location.href="/wechat-rewrite?c={cid}";</script>
    </body></html>
    ''')


@app.post("/wechat-rewrite/batch-rewrite")
async def wechat_rewrite_batch(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    """Rewrite all pending articles."""
    current = await resolve_channel(db, c)
    cid = current.id if current else 0
    if not cid:
        return channel_redirect("/wechat-rewrite", None)

    result = await db.execute(
        select(NewsItem).where(NewsItem.channel_id == cid, NewsItem.article_id == None)
    )
    pending = result.scalars().all()

    from app.comment_rewriter import CommentRewriter
    rewriter = CommentRewriter(channel=current, generator=DeepSeekGenerator())

    success = 0
    for item in pending:
        try:
            article_data = await rewriter.rewrite_item({
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "summary": item.summary,
                "content": item.content,
            })
            if article_data:
                title = article_data.get("title", item.title)
                summary = article_data.get("summary", "")
                content = article_data.get("content", "")
                cover = await generate_cover_image(title, "", source_name=current.name if current else "AI HOT")
                from app.scheduler import _md_to_html
                content_html = _md_to_html(content, title)

                article = Article(
                    channel_id=cid,
                    title=title,
                    content=content_html,
                    summary=summary,
                    cover_image=cover,
                    status="draft",
                    is_daily=False,
                )
                db.add(article)
                await db.flush()
                item.article_id = article.id
                success += 1
        except Exception as e:
            print(f"[BatchRewrite] Error on '{item.title}': {e}")

    await db.commit()
    return HTMLResponse(f'''
    <html><body>
    <script>alert("批量改写完成！成功 {success} 篇，失败 {len(pending) - success} 篇"); window.location.href="/wechat-rewrite?c={cid}";</script>
    </body></html>
    ''')


# ─── Channel upload helper ────────────────────────────────────────

async def _save_channel_uploads(channel: Channel, form):
    """Save uploaded avatar and QR code images for a channel."""
    import shutil
    ch_dir = CHANNEL_UPLOADS_DIR / str(channel.id)
    ch_dir.mkdir(parents=True, exist_ok=True)
    for field_name in ["avatar_image", "qrcode_image"]:
        upload = form.get(field_name)
        if upload is not None and hasattr(upload, "filename") and upload.filename:
            ext = os.path.splitext(upload.filename)[1] or ".png"
            filepath = ch_dir / f"{field_name}{ext}"
            with open(filepath, "wb") as f:
                shutil.copyfileobj(upload.file, f)
            setattr(channel, field_name, f"/data/channel_uploads/{channel.id}/{field_name}{ext}")


async def _save_channel_sources(session, channel_id: int, form):
    """Save all sources for a channel from form data.

    Form field convention:
      - Existing sources:    source_name_{id}, source_config_{id}, source_del_{id}
      - New source (optional): source_type_new, source_name_new, ws_keywords_new, etc.
    """
    from app.models import Source as Src

    # 1. Handle deletions (checkbox value = "1")
    for key in form.keys():
        if key.startswith("source_del_") and form.get(key) == "1":
            parts = key.split("_")
            if parts[-1] == "new":
                continue
            src_id = int(parts[-1])
            result = await session.execute(
                select(Src).where(Src.id == src_id, Src.channel_id == channel_id)
            )
            src = result.scalar_one_or_none()
            if src:
                await session.delete(src)

    # 2. Update existing sources
    for key in list(form.keys()):
        if key.startswith("source_name_"):
            parts = key.split("_")
            if parts[-1] == "new":
                continue
            src_id = int(parts[-1])
            # Skip if marked for deletion
            if form.get(f"source_del_{src_id}") == "1":
                continue
            result = await session.execute(
                select(Src).where(Src.id == src_id, Src.channel_id == channel_id)
            )
            src = result.scalar_one_or_none()
            if src:
                src.name = form.get(key, src.name)
                config_raw = form.get(f"source_config_{src_id}", "{}")
                try:
                    json.loads(config_raw)
                    src.config = config_raw
                except Exception:
                    pass

    # 3. Add new source (if name is provided)
    source_type = form.get("source_type_new", "").strip()
    source_name = form.get("source_name_new", "").strip()
    if not source_type or not source_name:
        return

    # Parse common filter keywords
    filter_keywords = [kw.strip() for kw in form.get("filter_keywords_new", "").strip().split("\n") if kw.strip()]

    # Build config JSON based on type
    if source_type == "wechat_sogou":
        keywords = [kw.strip() for kw in form.get("ws_keywords_new", "").strip().split("\n") if kw.strip()]
        accounts = [a.strip() for a in form.get("ws_accounts_new", "").strip().split("\n") if a.strip()]
        cfg = {
            "keywords": keywords,
            "wechat_accounts": accounts,
            "max_items": int(form.get("ws_max_items_new", 20)),
            "proxy": form.get("ws_proxy_new", ""),
        }
        if filter_keywords:
            cfg["filter_keywords"] = filter_keywords
        config = json.dumps(cfg, ensure_ascii=False)
    elif source_type == "html_scraper":
        cfg = {
            "url": form.get("hs_url_new", ""),
            "mode": form.get("hs_mode_new", "auto"),
            "list_xpath": form.get("hs_list_xpath_new", ""),
            "title_xpath": form.get("hs_title_xpath_new", ""),
            "content_xpath": form.get("hs_content_xpath_new", ""),
            "max_items": int(form.get("hs_max_items_new", 10)),
        }
        if filter_keywords:
            cfg["filter_keywords"] = filter_keywords
        config = json.dumps(cfg, ensure_ascii=False)
    else:
        try:
            cfg = json.loads(form.get("source_config_new", "{}"))
        except Exception:
            cfg = {}
        if filter_keywords:
            cfg["filter_keywords"] = filter_keywords
        config = json.dumps(cfg, ensure_ascii=False)

    src = Src(
        channel_id=channel_id,
        name=source_name,
        source_type=source_type,
        api_url=form.get("source_api_url_new", ""),
        api_key=form.get("source_api_key_new", ""),
        config=config,
        enabled=True,
    )
    session.add(src)


# ─── Channel management ─────────────────────────────────────────

@app.get("/channels")
async def channel_list(request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    return templates.TemplateResponse(request, "channels.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
    })


@app.get("/channels/add")
async def channel_add_form(request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    source_types = list_source_types()
    return templates.TemplateResponse(request, "channel_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "channel": None,
        "ch_sources": [],
        "source_types": source_types,
        "default_prompt": SYSTEM_PROMPT_FULL,
    })


@app.post("/channels/add")
async def channel_add(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    ch = Channel(
        name=form.get("name", ""),
        description=form.get("description", ""),
        writer_prompt=form.get("writer_prompt", ""),
        sticker_prompt=form.get("sticker_prompt", ""),
        schedule_hour=int(form.get("schedule_hour", 9)),
        schedule_minute=int(form.get("schedule_minute", 0)),
        schedule_enabled=form.get("schedule_enabled", "on") == "on",
        is_active=True,
    )
    db.add(ch)
    await db.flush()
    await _save_channel_uploads(ch, form)
    await _save_channel_sources(db, ch.id, form)
    await db.commit()
    return RedirectResponse(url="/channels", status_code=302)


@app.get("/channels/{channel_id}/edit")
async def channel_edit_form(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        return RedirectResponse(url="/channels", status_code=302)
    # Load all sources for this channel
    src_result = await db.execute(
        select(Source).where(Source.channel_id == channel_id).order_by(Source.id)
    )
    ch_sources = src_result.scalars().all()
    source_types = list_source_types()
    return templates.TemplateResponse(request, "channel_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "channel": ch,
        "ch_sources": ch_sources,
        "source_types": source_types,
        "default_prompt": SYSTEM_PROMPT_FULL,
    })


@app.post("/channels/{channel_id}/edit")
async def channel_edit(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        return RedirectResponse(url="/channels", status_code=302)
    form = await request.form()
    ch.name = form.get("name", ch.name)
    ch.description = form.get("description", ch.description)
    ch.writer_prompt = form.get("writer_prompt", ch.writer_prompt)
    ch.sticker_prompt = form.get("sticker_prompt", ch.sticker_prompt)
    ch.schedule_hour = int(form.get("schedule_hour", ch.schedule_hour))
    ch.schedule_minute = int(form.get("schedule_minute", ch.schedule_minute))
    ch.schedule_enabled = form.get("schedule_enabled", "on") == "on"
    await _save_channel_uploads(ch, form)
    await _save_channel_sources(db, ch.id, form)
    await db.commit()
    return RedirectResponse(url="/channels", status_code=302)


@app.post("/channels/{channel_id}/delete")
async def channel_delete(channel_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if ch:
        await db.delete(ch)
        await db.commit()
    return RedirectResponse(url="/channels", status_code=302)


# ─── WeChat Login per channel ──────────────────────────────────

@app.get("/channels/{channel_id}/wechat-login")
async def channel_wechat_login_page(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        return RedirectResponse(url="/channels", status_code=302)
    return templates.TemplateResponse(request, "wechat_login.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "channel": ch,
    })


@app.post("/channels/{channel_id}/wechat-login")
async def channel_wechat_login(channel_id: int):
    """Trigger WeChat login via Playwright browser."""
    from app.wechat_publisher import WeChatPublisher
    try:
        async with WeChatPublisher(channel_id=channel_id) as pub:
            await pub.ensure_login()
        return HTMLResponse(f'''
        <html><body>
        <script>alert("微信登录成功！频道 {channel_id} 的登录态已保存。"); window.location.href="/channels/{channel_id}/edit";</script>
        </body></html>
        ''')
    except Exception as e:
        return HTMLResponse(f'''
        <html><body>
        <script>alert("登录失败: {str(e).replace(chr(39), '')}"); window.location.href="/channels/{channel_id}/wechat-login";</script>
        </body></html>
        ''')


# ─── Manual run / trigger ────────────────────────────────────────

@app.post("/manual-run")
async def manual_run(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    from app.scheduler import daily_job_for_channel
    current = await resolve_channel(db, c)
    if not current:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JSONResponse({"ok": False, "error": "No channel"})
        return channel_redirect("/", None)
    try:
        await daily_job_for_channel(current.id, current.name)
        ok = True
        err = ""
    except Exception as e:
        ok = False
        err = str(e)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse({"ok": ok, "error": err, "channel_id": current.id})
    return channel_redirect("/", current.id)


@app.post("/trigger-generate")
async def trigger_generate(db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    where = [NewsItem.channel_id == cid] if cid else []
    result = await db.execute(
        select(NewsItem).where(*where).order_by(desc(NewsItem.created_at)).limit(50)
    )
    items = result.scalars().all()

    if not items:
        return channel_redirect("/", c)

    news_data = {
        "items": [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "summary": item.summary,
                "category": item.category,
                "publishedAt": item.published_at,
            }
            for item in items
        ],
        "daily": None,
        "date": "",
    }

    generator = DeepSeekGenerator()
    article_data = await generator.generate_article(news_data)

    if article_data:
        title = article_data.get("title", "AI 资讯")
        summary = article_data.get("summary", "")
        content = article_data.get("content", "")
        from app.scheduler import _md_to_html
        content_html = _md_to_html(content)
        cover = await generate_cover_image(title, "", source_name=current.name if current else "AI HOT")

        article = Article(
            channel_id=cid or None,
            title=title,
            content=content_html,
            summary=summary,
            cover_image=cover,
            status="draft",
            is_daily=False,
        )
        db.add(article)
        await db.commit()

    return channel_redirect("/", c)


# ─── Scheduler status ───────────────────────────────────────────

@app.get("/scheduler-status.json")
async def scheduler_status_json(db: AsyncSession = Depends(get_db)):
    from app.scheduler import scheduler_status as ss
    data = ss()
    channels = await db.execute(
        select(Channel).where(Channel.is_active == True, Channel.schedule_enabled == True)
    )
    data["channels"] = {str(ch.id): ch.name for ch in channels.scalars().all()}
    return JSONResponse(data)


@app.get("/scheduler-status")
async def scheduler_status_route():
    from app.scheduler import scheduler_status as ss
    data = ss()
    status = "running" if data["alive"] else "stopped"
    msg = (
        f"<h2>Scheduler: {status}</h2>"
        f"<pre>running_channels: {data['running']}</pre>"
        f"<pre>last_run: {data['last_run']}</pre>"
        f"<p><a href='/'>Back to dashboard</a></p>"
    )
    return HTMLResponse(msg)


# ─── Scheduler SSE events ──────────────────────────────────────

@app.get("/scheduler-events")
async def scheduler_events(request: Request):
    from app.scheduler import subscribe, unsubscribe
    import asyncio

    queue = subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Logs ────────────────────────────────────────────────────────

@app.get("/logs")
async def log_list(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    channels = await get_channels(db)
    current = await resolve_channel(db, c)
    cid = current.id if current else 0

    where = [DailyLog.channel_id == cid] if cid else []
    result = await db.execute(
        select(DailyLog).where(*where).order_by(desc(DailyLog.created_at)).limit(50)
    )
    logs = result.scalars().all()
    return templates.TemplateResponse(request, "logs.html", {
        "request": request,
        "channels": channels,
        "current_channel": current,
        "logs": logs,
    })
