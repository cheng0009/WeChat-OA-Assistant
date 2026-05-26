import os, json, urllib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, text
from pathlib import Path

from app.database import init_db, get_db
from app.models import Article, NewsItem, DailyLog, Source, Channel, WritingSkill
from app.config import settings, BASE_DIR, ARTICLES_DIR, IMAGES_DIR, WECHAT_IMAGES_DIR, CHANNEL_UPLOADS_DIR
from app.scheduler import start_scheduler, stop_scheduler, daily_job
from app.fetcher import test_source
from app.generator import DeepSeekGenerator, SYSTEM_PROMPT_FULL
from app.writing_skills import WritingSkillDef
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


async def resolve_channel_skill(db: AsyncSession, channel: Channel | None) -> WritingSkillDef | None:
    """Resolve the effective writing skill for a channel.
    Priority: channel skill > channel writer_prompt > default preset skill.
    """
    from sqlalchemy.orm import selectinload
    from app.writing_skills import skill_def_from_orm

    if not channel:
        return None

    # Reload with skill relationship
    result = await db.execute(
        select(Channel)
        .options(selectinload(Channel.writing_skill))
        .where(Channel.id == channel.id)
    )
    ch = result.scalar_one_or_none()
    if not ch:
        return None

    # Channel has a selected skill
    if ch.writing_skill_id and ch.writing_skill:
        return skill_def_from_orm(ch.writing_skill)

    # Channel has a custom writer_prompt (backward compat)
    if ch.writer_prompt:
        first_line = ch.writer_prompt.strip().split("\n")[0]
        persona = "老成"
        if "「" in first_line and "」" in first_line:
            persona = first_line.split("「")[1].split("」")[0]
        return WritingSkillDef(
            id=0, name="", description="", persona=persona,
            system_prompt=ch.writer_prompt,
            sticker_prompt=ch.sticker_prompt or "",
        )

    # Default: load preset skill
    result2 = await db.execute(
        select(WritingSkill).where(WritingSkill.is_preset == True)
        .order_by(WritingSkill.id).limit(1)
    )
    preset = result2.scalar_one_or_none()
    if preset:
        return skill_def_from_orm(preset)

    return None


def channel_redirect(path: str, channel_id: int | None = None) -> RedirectResponse:
    if channel_id:
        url = f"{path}?c={channel_id}"
    else:
        url = path
    return RedirectResponse(url=url, status_code=302)


# ─── Dashboard ───────────────────────────────────────────────────

@app.get("/")
async def index(request: Request, db: AsyncSession = Depends(get_db), c: int | None = Query(None)):
    import time as _time
    _t0 = _time.time()
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
    _elapsed = _time.time() - _t0
    if _elapsed > 1:
        print(f"[SLOW] / (dashboard for c={c}) took {_elapsed:.2f}s")


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
    skill_def = await resolve_channel_skill(db, current)
    rewriter = CommentRewriter(channel=current, generator=DeepSeekGenerator(), skill_def=skill_def)
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
            enhanced=article_data.get("enhanced", False),
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
    skill_def = await resolve_channel_skill(db, current)
    rewriter = CommentRewriter(channel=current, generator=DeepSeekGenerator(), skill_def=skill_def)

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
                    enhanced=article_data.get("enhanced", False),
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

    Returns a tuple (success: bool, message: str).
    """
    from app.models import Source as Src

    # Update existing sources
    for key in list(form.keys()):
        if key.startswith("source_name_"):
            parts = key.split("_")
            if parts[-1] == "new":
                continue
            src_id = int(parts[-1])
            result = await session.execute(
                select(Src).where(Src.id == src_id, Src.channel_id == channel_id)
            )
            src = result.scalar_one_or_none()
            if src:
                src.name = form.get(key, src.name)
                if f"ws_keywords_{src_id}" in form:
                    keywords = [kw.strip() for kw in form.get(f"ws_keywords_{src_id}", "").strip().split("\n") if kw.strip()]
                    accounts = [a.strip() for a in form.get(f"ws_accounts_{src_id}", "").strip().split("\n") if a.strip()]
                    max_items = int(form.get(f"ws_max_items_{src_id}", 20))
                    proxy = form.get(f"ws_proxy_{src_id}", "").strip()
                    cfg = {
                        "keywords": keywords,
                        "wechat_accounts": accounts,
                        "max_items": max_items,
                        "proxy": proxy,
                    }
                    try:
                        old_cfg = json.loads(src.config) if src.config else {}
                        if old_cfg.get("filter_keywords"):
                            cfg["filter_keywords"] = old_cfg["filter_keywords"]
                    except Exception:
                        pass
                    src.config = json.dumps(cfg, ensure_ascii=False)
                else:
                    config_raw = form.get(f"source_config_{src_id}", "{}")
                    try:
                        json.loads(config_raw)
                        src.config = config_raw
                    except Exception:
                        pass

    # 3. Add new source (only if name is provided)
    source_name = form.get("source_name_new", "").strip()
    if source_name:
        source_type = form.get("source_type_new", "").strip()
        if not source_type:
            return False, "来源类型不能为空"

        filter_keywords = [kw.strip() for kw in form.get("filter_keywords_new", "").strip().split("\n") if kw.strip()]

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
    return True, "数据源保存成功"


# ─── Writing skill management ─────────────────────────────────────

@app.get("/writing-skills")
async def writing_skill_list(request: Request, db: AsyncSession = Depends(get_db)):
    import time as _time
    _t0 = _time.time()
    channels = await get_channels(db)
    result = await db.execute(select(WritingSkill).order_by(WritingSkill.id))
    skills = result.scalars().all()
    _elapsed = _time.time() - _t0
    if _elapsed > 1:
        print(f"[SLOW] /writing-skills took {_elapsed:.2f}s")
    return templates.TemplateResponse(request, "writing_skills.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "skills": skills,
    })


@app.get("/writing-skills/add")
async def writing_skill_add_form(request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    from app.writing_skills import DEFAULT_STYLE_GUIDE, DEFAULT_QUALITY_CHECKLIST
    from app.generator import SYSTEM_PROMPT_FULL, STICKER_SYSTEM_PROMPT
    return templates.TemplateResponse(request, "writing_skill_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "skill": None,
        "default_system_prompt": SYSTEM_PROMPT_FULL,
        "default_sticker_prompt": STICKER_SYSTEM_PROMPT,
        "default_style_guide": DEFAULT_STYLE_GUIDE,
        "default_quality_checklist": DEFAULT_QUALITY_CHECKLIST,
    })


@app.post("/writing-skills/add")
async def writing_skill_add(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    skill = WritingSkill(
        is_preset=False,
        name=form.get("name", ""),
        description=form.get("description", ""),
        persona=form.get("persona", "老成"),
        system_prompt=form.get("system_prompt", ""),
        sticker_prompt=form.get("sticker_prompt", ""),
        style_guide=form.get("style_guide", ""),
        quality_checklist=form.get("quality_checklist", ""),
    )
    db.add(skill)
    await db.commit()
    return RedirectResponse(url="/writing-skills", status_code=302)


@app.get("/writing-skills/{skill_id}/edit")
async def writing_skill_edit_form(skill_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    import time as _time
    _t0 = _time.time()
    channels = await get_channels(db)
    result = await db.execute(select(WritingSkill).where(WritingSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        return RedirectResponse(url="/writing-skills", status_code=302)
    from app.writing_skills import DEFAULT_STYLE_GUIDE, DEFAULT_QUALITY_CHECKLIST
    _elapsed = _time.time() - _t0
    if _elapsed > 1:
        print(f"[SLOW] /writing-skills/{skill_id}/edit took {_elapsed:.2f}s")
    return templates.TemplateResponse(request, "writing_skill_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "skill": skill,
        "default_style_guide": DEFAULT_STYLE_GUIDE,
        "default_quality_checklist": DEFAULT_QUALITY_CHECKLIST,
    })


@app.post("/writing-skills/{skill_id}/edit")
async def writing_skill_edit(skill_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WritingSkill).where(WritingSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        return RedirectResponse(url="/writing-skills", status_code=302)
    form = await request.form()
    skill.name = form.get("name", skill.name)
    skill.description = form.get("description", skill.description)
    skill.persona = form.get("persona", skill.persona)
    skill.system_prompt = form.get("system_prompt", skill.system_prompt)
    skill.sticker_prompt = form.get("sticker_prompt", skill.sticker_prompt)
    skill.style_guide = form.get("style_guide", skill.style_guide)
    skill.quality_checklist = form.get("quality_checklist", skill.quality_checklist)
    await db.commit()
    return RedirectResponse(url="/writing-skills", status_code=302)


@app.post("/writing-skills/{skill_id}/delete")
async def writing_skill_delete(skill_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WritingSkill).where(WritingSkill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill and not skill.is_preset:
        # Unlink any channels using this skill
        await db.execute(
            text("UPDATE channels SET writing_skill_id = NULL WHERE writing_skill_id = :sid"),
            {"sid": skill_id},
        )
        await db.delete(skill)
        await db.commit()
    return RedirectResponse(url="/writing-skills", status_code=302)


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
    result = await db.execute(select(WritingSkill).order_by(WritingSkill.id))
    all_skills = result.scalars().all()
    return templates.TemplateResponse(request, "channel_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "channel": None,
        "ch_sources": [],
        "source_types": source_types,
        "default_prompt": SYSTEM_PROMPT_FULL,
        "all_skills": all_skills,
    })


@app.post("/channels/add")
async def channel_add(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    sid_raw = form.get("writing_skill_id", "")
    ch = Channel(
        name=form.get("name", ""),
        description=form.get("description", ""),
        writer_prompt=form.get("writer_prompt", ""),
        sticker_prompt=form.get("sticker_prompt", ""),
        writing_skill_id=int(sid_raw) if sid_raw and sid_raw != "0" else None,
        schedule_hour=int(form.get("schedule_hour", 9)),
        schedule_minute=int(form.get("schedule_minute", 0)),
        schedule_enabled=form.get("schedule_enabled", "on") == "on",
        is_active=True,
    )
    db.add(ch)
    await db.flush()
    await _save_channel_uploads(ch, form)
    ok, msg = await _save_channel_sources(db, ch.id, form)
    await db.commit()
    url = "/channels"
    if not ok:
        url += f"?msg={urllib.parse.quote(msg)}&type=warning"
    return RedirectResponse(url=url, status_code=302)


@app.get("/channels/{channel_id}/edit")
async def channel_edit_form(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channels = await get_channels(db)
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Channel)
        .options(selectinload(Channel.writing_skill))
        .where(Channel.id == channel_id)
    )
    ch = result.scalar_one_or_none()
    if not ch:
        return RedirectResponse(url="/channels", status_code=302)
    # Load all sources for this channel
    src_result = await db.execute(
        select(Source).where(Source.channel_id == channel_id).order_by(Source.id)
    )
    ch_sources = src_result.scalars().all()
    source_types = list_source_types()
    result2 = await db.execute(select(WritingSkill).order_by(WritingSkill.id))
    all_skills = result2.scalars().all()
    return templates.TemplateResponse(request, "channel_form.html", {
        "request": request,
        "channels": channels,
        "current_channel": None,
        "channel": ch,
        "ch_sources": ch_sources,
        "source_types": source_types,
        "default_prompt": SYSTEM_PROMPT_FULL,
        "all_skills": all_skills,
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
    sid_raw = form.get("writing_skill_id", "")
    ch.writing_skill_id = int(sid_raw) if sid_raw and sid_raw != "0" else None
    ch.schedule_hour = int(form.get("schedule_hour", ch.schedule_hour))
    ch.schedule_minute = int(form.get("schedule_minute", ch.schedule_minute))
    ch.schedule_enabled = form.get("schedule_enabled", "on") == "on"
    await _save_channel_uploads(ch, form)
    ok, msg = await _save_channel_sources(db, ch.id, form)
    await db.commit()
    url = "/channels"
    if not ok:
        url += f"?msg={urllib.parse.quote(msg)}&type=warning"
    return RedirectResponse(url=url, status_code=302)


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

    skill_def = await resolve_channel_skill(db, current)
    generator = DeepSeekGenerator()
    article_data = await generator.generate_article(news_data, skill=skill_def)

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


# ─── Test source ─────────────────────────────────────────────────

@app.post("/sources/{source_id}/test")
async def test_source_endpoint(source_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Test a specific source by fetching data."""
    from app.fetcher import test_source as fetcher_test_source
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        try:
            result = await fetcher_test_source(source_id)
            return JSONResponse({"ok": True, "result": result})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})
    return HTMLResponse("<script>alert('请使用 AJAX');window.history.back();</script>")


@app.post("/sources/{source_id}/delete")
async def delete_source_endpoint(source_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete a specific source via AJAX."""
    from app.models import Source as Src
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        try:
            result = await db.execute(select(Src).where(Src.id == source_id))
            src = result.scalar_one_or_none()
            if not src:
                return JSONResponse({"ok": False, "error": "数据源不存在"})
            await db.delete(src)
            await db.commit()
            return JSONResponse({"ok": True, "message": "删除成功"})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})
    return HTMLResponse("<script>alert('请使用 AJAX');window.history.back();</script>")


# ─── Scheduler status ───────────────────────────────────────────

@app.get("/scheduler-status.json")
async def scheduler_status_json(db: AsyncSession = Depends(get_db)):
    from app.scheduler import scheduler_status as ss
    data = ss()
    # Build running_channels dict {id: name} for currently running jobs
    running_ids = data.get("running", [])
    if running_ids:
        ch_result = await db.execute(
            select(Channel).where(Channel.id.in_(running_ids))
        )
        running_map = {str(ch.id): ch.name for ch in ch_result.scalars().all()}
    else:
        running_map = {}
    data["running_channels"] = running_map
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
