import datetime
import traceback
import json
import asyncio

from app.config import settings
from sqlalchemy import select
from app.database import async_session
from app.models import Article, NewsItem, DailyLog, Source, Channel
from app.fetcher import fetch_from_all_sources
from app.generator import DeepSeekGenerator
from app.image_gen import generate_cover_image
from app.wechat_image_gen import generate_wechat_images, DEFAULT_STYLE
from app.writing_skills import WritingSkillDef, skill_def_from_orm

CHANNEL_MAX_ARTICLES = 12

_cron_task: asyncio.Task | None = None
_last_fire_date: dict[int, str] = {}  # channel_id -> YYYY-MM-DD of last fire
_running_channels: set[int] = set()  # channels currently being processed

async def daily_job_for_channel(channel_id: int, channel_name: str = ""):
    """Run daily job for a specific channel: fetch -> generate -> images."""
    _running_channels.add(channel_id)
    print(f"[Scheduler] Starting daily job for channel {channel_id} at {datetime.datetime.now()}")
    try:
        async with async_session() as session:
            from sqlalchemy.orm import selectinload
            result = await session.execute(
                select(Channel)
                .options(selectinload(Channel.writing_skill))
                .where(Channel.id == channel_id)
            )
            channel = result.scalar_one_or_none()
            if not channel:
                print(f"[Scheduler] Channel {channel_id} not found")
                return

        generator = DeepSeekGenerator()

        try:
            result = await session.execute(
                select(Source).where(Source.channel_id == channel_id, Source.enabled == True)
            )
            rows = result.scalars().all()

            source_buckets = []
            for src_row in rows:
                from app.sources import get_source_class
                cls = get_source_class(src_row.source_type)
                config = json.loads(src_row.config) if src_row.config else {}
                inst = cls(api_url=src_row.api_url, api_key=src_row.api_key or "", config=config)
                try:
                    items = await inst.fetch()
                    source_buckets.append(items)
                finally:
                    if hasattr(inst, "close"):
                        await inst.close()

            all_items = []
            seen_urls = set()
            num_buckets = len(source_buckets)

            if num_buckets > 0:
                per_source = CHANNEL_MAX_ARTICLES // num_buckets
                extra_seats = CHANNEL_MAX_ARTICLES % num_buckets
                quotas = [per_source + (1 if i < extra_seats else 0) for i in range(num_buckets)]
                taken = [0] * num_buckets
                cursors = [0] * num_buckets

                while len(all_items) < CHANNEL_MAX_ARTICLES:
                    any_progress = False
                    for i in range(num_buckets):
                        if len(all_items) >= CHANNEL_MAX_ARTICLES:
                            break
                        if taken[i] >= quotas[i]:
                            continue
                        while cursors[i] < len(source_buckets[i]):
                            item = source_buckets[i][cursors[i]]
                            cursors[i] += 1
                            url = item.get("url", "")
                            if url and url in seen_urls:
                                continue
                            seen_urls.add(url)
                            all_items.append(item)
                            taken[i] += 1
                            any_progress = True
                            break

                    if not any_progress:
                        break

                if len(all_items) < CHANNEL_MAX_ARTICLES:
                    remaining = CHANNEL_MAX_ARTICLES - len(all_items)
                    for i in range(num_buckets):
                        if remaining <= 0:
                            break
                        while cursors[i] < len(source_buckets[i]) and remaining > 0:
                            item = source_buckets[i][cursors[i]]
                            cursors[i] += 1
                            url = item.get("url", "")
                            if url and url in seen_urls:
                                continue
                            seen_urls.add(url)
                            all_items.append(item)
                            remaining -= 1

            if not all_items:
                print(f"[Scheduler] No news data for channel {channel_id}")
                return

            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            folder_date = datetime.datetime.now().strftime("%Y-%m-%d")
            news_data = {"items": all_items, "daily": None, "date": date_str}

            # Filter out items whose URL already used in a previous article
            if all_items:
                cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
                existing_rows = await session.execute(
                    select(NewsItem.url).where(
                        NewsItem.channel_id == channel_id,
                        NewsItem.url != "",
                        NewsItem.created_at >= cutoff,
                    )
                )
                existing_urls = {row[0] for row in existing_rows.fetchall() if row[0]}

                before = len(all_items)
                all_items = [it for it in all_items if it.get("url", "") not in existing_urls]
                skipped = before - len(all_items)
                if skipped:
                    print(f"[Scheduler] Skipped {skipped} items already used in previous articles")
                news_data["items"] = all_items

            if len(all_items) < 3:
                print(f"[Scheduler] ⚠️ 频道 {channel_id} 仅 {len(all_items)} 篇可用素材，建议添加更多数据源")
                daily_log = DailyLog(
                    channel_id=channel_id,
                    date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    fetch_count=len(all_items),
                    status="warning",
                    message=f"素材太少（{len(all_items)}篇），无法生成文章。请在频道中添加更多关键词、公众号或其他数据源。",
                )
                session.add(daily_log)
                await session.commit()
                return

            # Resolve writing skill
            skill_def = None
            if channel.writing_skill_id and channel.writing_skill:
                skill_def = skill_def_from_orm(channel.writing_skill)
            elif channel.writer_prompt:
                first_line = channel.writer_prompt.strip().split("\n")[0]
                persona = "老成"
                if "「" in first_line and "」" in first_line:
                    persona = first_line.split("「")[1].split("」")[0]
                skill_def = WritingSkillDef(
                    id=0, name="", description="", persona=persona,
                    system_prompt=channel.writer_prompt,
                    sticker_prompt=channel.sticker_prompt or "",
                )

            # Default to preset skill if nothing configured
            if not skill_def:
                from app.models import WritingSkill
                result2 = await session.execute(
                    select(WritingSkill).where(WritingSkill.is_preset == True)
                    .order_by(WritingSkill.id).limit(1)
                )
                preset = result2.scalar_one_or_none()
                if preset:
                    skill_def = skill_def_from_orm(preset)

            article_data = await generator.generate_article(news_data, skill=skill_def)

            if article_data:
                content_long = article_data.get("content", "")
                title = article_data.get("title", f"日报 {date_str}")
                viral_title = article_data.get("viral_title", title)
                summary = article_data.get("summary", "")

                content_html = _md_to_html(content_long, viral_title or title)

                sticker_text = await generator.generate_sticker(content_long, skill=skill_def)
                import re as _re
                sticker_text = _re.sub(r"\n{3,}", "\n\n", sticker_text.strip())

                cover_path = await generate_cover_image(viral_title, folder_date, source_name=channel.name)

                wechat_files = await generate_wechat_images(
                    title, viral_title, sticker_text, folder_date,
                    avatar_path=channel.avatar_image or None,
                    qrcode_path=channel.qrcode_image or None,
                    date_prefix=channel.name,
                )
                wechat_urls = ",".join(w for w in wechat_files)

                article = Article(
                    channel_id=channel_id,
                    title=title,
                    viral_title=viral_title,
                    content=content_html,
                    sticker_content=sticker_text,
                    image_style=DEFAULT_STYLE,
                    summary=summary,
                    cover_image=cover_path,
                    wechat_images=wechat_urls,
                    source_date=date_str,
                    status="draft",
                    is_daily=True,
                    enhanced=article_data.get("enhanced", False),
                )
                session.add(article)
                await session.flush()

                for item in news_data.get("items", []):
                    news_item = NewsItem(
                        channel_id=channel_id,
                        article_id=article.id,
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        source=item.get("source", ""),
                        summary=item.get("summary", ""),
                        category=item.get("category", ""),
                        published_at=item.get("publishedAt", ""),
                        raw_date=date_str,
                    )
                    session.add(news_item)

                daily_log = DailyLog(
                    channel_id=channel_id, date=date_str,
                    fetch_count=len(news_data.get("items", [])),
                    article_id=article.id,
                    status="success", message=f"Generated article: {title}",
                )
                session.add(daily_log)
                await session.commit()
                print(f"[Scheduler] Article generated for channel {channel_id}: {title}")

                # Auto-publish to WeChat
                pub_result = await _auto_publish_article(session, article, channel_id)
                daily_log.message += f"; auto-publish: {pub_result}"
                await session.commit()
            else:
                daily_log = DailyLog(
                    channel_id=channel_id, date=date_str,
                    fetch_count=len(news_data.get("items", [])),
                    status="warning", message="Fetched data but failed to generate article",
                )
                session.add(daily_log)
                await session.commit()

        except Exception as e:
            print(f"[Scheduler] Error for channel {channel_id}: {e}")
            traceback.print_exc()
            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            daily_log = DailyLog(
                channel_id=channel_id, date=date_str,
                status="error", message=str(e)[:500],
            )
            session.add(daily_log)
            await session.commit()
    finally:
        _running_channels.discard(channel_id)


async def _auto_publish_article(session, article, channel_id: int) -> str:
    """Auto-publish article + sticker to WeChat. Marks article on failure.
    Returns a short result string for the DailyLog.
    """
    from app.wechat_publisher import WeChatPublisher, LoginRequiredError
    from app.config import DATA_DIR

    state_file = DATA_DIR / f"wechat_state_{channel_id}.json"
    if not state_file.exists():
        article.auto_publish_note = "no_login"
        print(f"[Scheduler] Auto-publish skipped for channel {channel_id} (no login session)")
        return "no_login"

    try:
        async with WeChatPublisher(channel_id=channel_id, headless=True) as pub:
            draft_url = await pub.publish(article)
            article.wechat_draft_url = draft_url
            article.wechat_published = True
            print(f"[Scheduler] Article published to WeChat draft for channel {channel_id}")

            result = "article"
            if article.wechat_images:
                try:
                    sticker_url = await pub.publish_sticker(article)
                    article.wechat_sticker_url = sticker_url
                    article.wechat_sticker_published = True
                    result = "article+sticker"
                    print(f"[Scheduler] Sticker published to WeChat draft for channel {channel_id}")
                except LoginRequiredError:
                    print(f"[Scheduler] Sticker publish skipped (login required), article was published")
                    result = "article_only"
                except Exception as e2:
                    print(f"[Scheduler] Sticker publish failed: {e2}")
                    result = "article_only"

            article.auto_publish_note = ""
            print(f"[Scheduler] Auto-publish success for channel {channel_id}")
            return result
    except LoginRequiredError:
        article.auto_publish_note = "no_login"
        print(f"[Scheduler] Auto-publish skipped for channel {channel_id} (login required)")
        return "no_login"
    except Exception as e:
        article.auto_publish_note = f"failed: {str(e)[:120]}"
        print(f"[Scheduler] Auto-publish failed for channel {channel_id}: {e}")
        traceback.print_exc()
        return f"failed: {str(e)[:80]}"


async def daily_job(source_type: str = ""):
    """Legacy: run daily job for first active channel (for backward compat)."""
    async with async_session() as session:
        result = await session.execute(select(Channel).order_by(Channel.id).limit(1))
        ch = result.scalar_one_or_none()
        if ch:
            await daily_job_for_channel(ch.id, ch.name)


# ── Cron loop (replaces APScheduler CronTrigger) ──────────────

async def start_scheduler():
    """Start the daily cron loop as a background task."""
    global _cron_task
    if _cron_task is not None:
        return
    _cron_task = asyncio.create_task(_cron_loop())
    print("[Scheduler] Cron loop started")


def stop_scheduler():
    """Cancel the cron loop task."""
    global _cron_task
    if _cron_task:
        _cron_task.cancel()
        _cron_task = None
        print("[Scheduler] Cron loop stopped")


async def _cron_loop():
    """Check every 30 seconds if any channel's daily job should fire."""
    while True:
        try:
            now = datetime.datetime.now()

            async with async_session() as session:
                result = await session.execute(
                    select(Channel).where(Channel.is_active == True, Channel.schedule_enabled == True)
                )
                channels = result.scalars().all()

            for ch in channels:
                scheduled = now.replace(hour=ch.schedule_hour, minute=ch.schedule_minute, second=0, microsecond=0)
                window_start = scheduled - datetime.timedelta(minutes=5)
                window_end = scheduled + datetime.timedelta(minutes=30)  # 5min 前到 30min 后，小宕机可补发
                today = now.strftime("%Y-%m-%d")
                if window_start <= now <= window_end and _last_fire_date.get(ch.id) != today:
                    _last_fire_date[ch.id] = today
                    print(f"[Scheduler] Firing daily job for '{ch.name}' at {now}")
                    asyncio.create_task(daily_job_for_channel(ch.id, ch.name))

        except Exception as e:
            print(f"[Scheduler] Cron loop error: {e}")
            traceback.print_exc()

        await asyncio.sleep(30)


# ── Scheduler status (for /scheduler-status endpoint) ──────────

def scheduler_status() -> dict:
    """Return current scheduler state for diagnostics."""
    return {
        "alive": _cron_task is not None and not _cron_task.done(),
        "last_run": {str(k): v for k, v in _last_fire_date.items()},
        "running": list(_running_channels),
    }


# ── Unscheduled manual fire (for the /manual-run endpoint) ────

async def fire_channel_now(channel_id: int) -> str:
    """Run daily_job_for_channel and return the result message."""
    try:
        await daily_job_for_channel(channel_id)
        return "ok"
    except Exception as e:
        return f"error: {e}"


# ── Markdown to HTML helpers (used elsewhere too) ─────────────

def _md_to_html(md: str, article_title: str = "") -> str:
    import re

    lines = md.strip().split("\n")
    body_lines = []
    for line in lines:
        if line.strip().startswith("# ") and not line.strip().startswith("## "):
            continue
        body_lines.append(line)

    body_md = "\n".join(body_lines)
    html = body_md

    html = re.sub(r"^### (.+)$", lambda m: _mdnice_h3(m.group(1)), html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", lambda m: _mdnice_h2(m.group(1)), html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", lambda m: _mdnice_bold(m.group(1)), html)
    html = re.sub(r"^---+\s*$", _mdnice_hr, html, flags=re.MULTILINE)
    html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" style="color: rgb(0, 150, 136); text-decoration: none;">\1</a>', html)

    blocks = re.split(r"\n\n+", html)
    processed = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("<h2") or block.startswith("<h3") or block.startswith("<hr") or block.startswith("<"):
            processed.append(block)
        else:
            processed.append(_mdnice_paragraph(block))

    sub_title = article_title or "资讯日报"
    date_str = datetime.datetime.now().strftime("%Y年%m月%d日")

    wrapped = f"""<section style="margin: 0; padding: 10px; font-family: Optima, 'Microsoft YaHei', PingFangSC-regular, serif; font-size: 16px; color: rgb(0, 0, 0); line-height: 1.5em; word-break: break-word; overflow-wrap: break-word; text-align: left;">
<h1 style="margin: 30px 0 15px; padding: 0; font-size: 22px; color: rgb(0, 150, 136); line-height: 1.5em; text-align: center; border-bottom: 1px solid rgb(0, 150, 136); padding-bottom: 10px; font-weight: bold; letter-spacing: 0em;">{sub_title}</h1>
<blockquote style="margin: 20px 0; padding: 10px 20px; border-left: 3px solid rgb(0, 150, 136); border-right: 3px solid rgba(0, 150, 136, 0.3); border-top: 3px solid rgba(0, 0, 0, 0.4); border-bottom: 3px solid rgba(0, 0, 0, 0.4); background: rgba(0, 0, 0, 0.05);">
<p style="margin: 0; padding: 0; color: rgb(119, 119, 119); font-size: 16px; line-height: 1.8em;">{date_str}</p>
</blockquote>
{"\n\n".join(processed)}
</section>"""
    return wrapped


def _mdnice_h3(text: str) -> str:
    return f'<h3 style="margin: 25px 0 12px; padding: 0; font-size: 18px; color: rgb(0, 0, 0); line-height: 1.8em; font-weight: bold;">{text}</h3>'


def _mdnice_h2(text: str) -> str:
    return f'<h2 style="margin: 30px 0 15px; padding: 0 0 0 10px; font-size: 20px; color: rgb(0, 150, 136); line-height: 1.8em; font-weight: bold; border-left: 3px solid rgb(0, 150, 136);">{text}</h2>'


def _mdnice_bold(text: str) -> str:
    return f'<strong style="color: rgb(0, 150, 136); font-weight: bold;">{text}</strong>'


def _mdnice_hr(match=None) -> str:
    return '<hr style="margin: 10px 0; border: none; border-top: 1px solid rgb(0, 0, 0);">'


def _mdnice_paragraph(text: str) -> str:
    text = text.replace("\n", "<br>")
    return f'<p style="margin: 0; padding: 8px 0; color: rgb(0, 0, 0); font-size: 16px; line-height: 1.8em; letter-spacing: 0em; text-align: justify; text-indent: 0em;">{text}</p>'
