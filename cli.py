"""
CLI 控制界面 — 通过终端命令控制 AI HOT 公众号助手

适用于 WeChat clawbot / SSH 手机远程控制。
"""
import asyncio, sys, os, json, shutil
from datetime import datetime
from license_check import check_license_with_exit

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure app can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select, desc, func
from app.database import async_session, init_db
from app.models import Article, DailyLog, Source
from app.config import BASE_DIR, WECHAT_IMAGES_DIR
from app.scheduler import scheduler, daily_job
from app.fetcher import fetch_from_all_sources, test_source
from app.sources import list_source_types, get_source_class


def _sep(title=""):
    sep = "━" * 40
    if title:
        return f"\n{sep}\n  {title}\n{sep}"
    return f"\n{sep}"


async def _preview_article(article_id: int, show_full=False, show_sticker=False, show_images=False):
    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        a = r.scalar_one_or_none()
        if not a:
            print("文章不存在")
            return
        print(_sep(f"文章 #{a.id}"))
        print(f"标题: {a.viral_title or a.title}")
        print(f"状态: {'已发布' if a.status == 'published' else '草稿'}")
        print(f"日期: {a.source_date or a.created_at.strftime('%Y-%m-%d')}")
        print(f"配图: {len(a.wechat_images.split(',')) if a.wechat_images else 0} 张")

        if show_full and a.content:
            print(_sep("完整长文"))
            import re
            plain = re.sub(r"<[^>]+>", "", a.content)
            print(plain)
        elif show_sticker and a.sticker_content:
            print(_sep("贴图文字"))
            print(a.sticker_content)
        elif show_images and a.wechat_images:
            print(_sep("配图 URL"))
            for i, url in enumerate(a.wechat_images.split(","), 1):
                print(f"  {i}. {url}")
        else:
            if a.sticker_content:
                txt = a.sticker_content[:300]
                print(_sep("贴图文字 (前300字)"))
                print(txt + ("..." if len(a.sticker_content) > 300 else ""))
            print(f"\n提示: 用 --full / --sticker / --images 查看完整内容")
        print()


async def _publish_article(article_id: int):
    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        a = r.scalar_one_or_none()
        if not a:
            print("文章不存在")
            return
        a.status = "published"
        await db.commit()
        print(f"文章 #{article_id} 已发布")


async def _delete_article(article_id: int):
    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        a = r.scalar_one_or_none()
        if not a:
            print("文章不存在")
            return
        await db.delete(a)
        await db.commit()
        print(f"文章 #{article_id} 已删除")


async def _export_images(article_id: int):
    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        a = r.scalar_one_or_none()
        if not a or not a.wechat_images:
            print("没有可导出的配图")
            return
        export_dir = os.path.join(
            str(BASE_DIR), "exported_images",
            f"{a.source_date or datetime.now().strftime('%Y-%m-%d')}-{a.id}"
        )
        os.makedirs(export_dir, exist_ok=True)
        count = 0
        for url_path in a.wechat_images.split(","):
            rel = url_path.replace("/data/wechat/", "").replace("\\", "/")
            src = os.path.join(str(WECHAT_IMAGES_DIR), rel)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(export_dir, os.path.basename(rel)))
                count += 1
        print(f"已导出 {count} 张图片到: {export_dir}")


async def _list_articles():
    async with async_session() as db:
        r = await db.execute(select(Article).order_by(desc(Article.created_at)).limit(20))
        articles = r.scalars().all()
        if not articles:
            print("暂无文章")
            return
        print(_sep("最近文章"))
        for a in articles:
            img_count = len(a.wechat_images.split(",")) if a.wechat_images else 0
            status = "[pub]" if a.status == "published" else "[dft]"
            print(f"  {a.id:>3} | {status} | {(a.viral_title or a.title)[:30]:30s} | {img_count}张贴图 | {a.source_date or ''}")
        print()


async def _list_sources():
    async with async_session() as db:
        r = await db.execute(select(Source).order_by(Source.created_at))
        sources = r.scalars().all()
        if not sources:
            print("暂无来源")
            return
        print(_sep("文章来源"))
        for s in sources:
            status = "[x]" if s.enabled else "[ ]"
            fetch_status = ""
            if s.last_fetch_at:
                fetch_status = f" | 上次: {s.last_fetch_at.strftime('%m-%d %H:%M')}"
                if s.last_fetch_ok == False:
                    fetch_status += " [失败]"
            print(f"  {s.id:>3} | {status} | {s.name:20s} | {s.source_type:8s} | {s.api_url[:40]}{fetch_status}")
        print()


async def _add_source(source_type: str, api_url: str, name: str = ""):
    types = [t["type_id"] for t in list_source_types()]
    if source_type not in types:
        print(f"未知来源类型: {source_type}，可用: {', '.join(types)}")
        return
    async with async_session() as db:
        src = Source(
            name=name or f"{source_type} #{datetime.now().strftime('%H%M%S')}",
            source_type=source_type,
            api_url=api_url,
            enabled=True,
        )
        db.add(src)
        await db.commit()
        print(f"已添加来源 #{src.id}: {src.name} ({source_type})")


async def _remove_source(source_id: int):
    async with async_session() as db:
        r = await db.execute(select(Source).where(Source.id == source_id))
        s = r.scalar_one_or_none()
        if not s:
            print("来源不存在")
            return
        await db.delete(s)
        await db.commit()
        print(f"来源 #{source_id} 已删除")


async def _test_source(source_id: int):
    msg = await test_source(source_id)
    print(msg)


async def _scheduler_status():
    running = scheduler.running
    jobs = scheduler.get_jobs()
    print(_sep("调度器状态"))
    print(f"运行中: {'是' if running else '否'}")
    for j in jobs:
        print(f"  任务: {j.id} | 下次触发: {j.next_run_time}")
    if not jobs:
        print("  无定时任务")
    print()
    # Also show last run
    async with async_session() as db:
        r = await db.execute(select(DailyLog).order_by(desc(DailyLog.created_at)).limit(3))
        logs = r.scalars().all()
        if logs:
            print("最近运行记录:")
            for log in logs:
                print(f"  {log.date} | {log.status} | {log.message[:50]}")


async def _status():
    async with async_session() as db:
        # Counts
        articles_total = (await db.execute(select(func.count(Article.id)))).scalar() or 0
        articles_pub = (await db.execute(select(func.count(Article.id)).where(Article.status == "published"))).scalar() or 0
        sources_total = (await db.execute(select(func.count(Source.id)))).scalar() or 0
        sources_enabled = (await db.execute(select(func.count(Source.id)).where(Source.enabled == True))).scalar() or 0
        log = (await db.execute(select(DailyLog).order_by(desc(DailyLog.created_at)).limit(1))).scalar_one_or_none()

    print(_sep("系统状态"))
    print(f"调度器: {'开启' if scheduler.running else '关闭'}"
          + (f" (每日 {_job_time()})" if scheduler.running else ""))
    print(f"文章来源: {sources_enabled}个启用 / {sources_total}个总数")
    print(f"文章总数: {articles_total}篇 (已发布 {articles_pub}篇)")
    if log:
        print(f"最后运行: {log.date} | {log.status} | {log.message[:60]}")
    print()


def _job_time():
    from app.config import settings
    return f"{settings.schedule_hour:02d}:{settings.schedule_minute:02d}"


async def _scheduler_on():
    if not scheduler.running:
        from app.scheduler import start_scheduler
        start_scheduler()
        print("调度器已开启")
    else:
        print("调度器已在运行中")


async def _scheduler_off():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("调度器已关闭")
    else:
        print("调度器未运行")


# ── WeChat helpers ───────────────────────────────────────────

async def _wechat_login():
    from app.wechat_publisher import wechat_login
    await wechat_login()


async def _wechat_upload(article_id: int):
    from sqlalchemy import select
    from app.database import async_session
    from app.models import Article
    from app.wechat_publisher import wechat_upload

    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        article = r.scalar_one_or_none()
    if not article:
        print("文章不存在")
        return

    print(f"[WeChat] Uploading article #{article_id}: {article.viral_title or article.title}")
    draft_url = await wechat_upload(article)

    async with async_session() as db:
        r = await db.execute(select(Article).where(Article.id == article_id))
        a = r.scalar_one_or_none()
        if a and draft_url:
            a.wechat_draft_url = draft_url
            await db.commit()
            print(f"[WeChat] Draft URL saved: {draft_url}")


async def _wechat_status():
    from app.wechat_publisher import wechat_status
    await wechat_status()


async def main():
    check_license_with_exit()
    if len(sys.argv) < 2:
        print(__doc__)
        return

    await init_db()
    cmd = sys.argv[1]

    if cmd == "run":
        print("正在执行 daily_job...")
        await daily_job()
        print("完成")

    elif cmd == "status":
        await _status()

    elif cmd == "articles" and len(sys.argv) >= 3:
        sub = sys.argv[2]
        if sub == "list":
            await _list_articles()
        elif sub == "show" and len(sys.argv) >= 4:
            aid = int(sys.argv[3])
            show_full = "--full" in sys.argv
            show_sticker = "--sticker" in sys.argv
            show_images = "--images" in sys.argv
            await _preview_article(aid, show_full, show_sticker, show_images)
        elif sub == "publish" and len(sys.argv) >= 4:
            await _publish_article(int(sys.argv[3]))
        elif sub == "export" and len(sys.argv) >= 4:
            await _export_images(int(sys.argv[3]))
        elif sub == "delete" and len(sys.argv) >= 4:
            await _delete_article(int(sys.argv[3]))
        else:
            print("用法: python cli.py articles <list|show|publish|export|delete> [id]")

    elif cmd == "sources" and len(sys.argv) >= 3:
        sub = sys.argv[2]
        if sub == "list":
            await _list_sources()
        elif sub == "add" and len(sys.argv) >= 5:
            src_type = sys.argv[3]
            url = sys.argv[4]
            name = sys.argv[5] if len(sys.argv) >= 6 else ""
            await _add_source(src_type, url, name)
        elif sub == "remove" and len(sys.argv) >= 4:
            await _remove_source(int(sys.argv[3]))
        elif sub == "test" and len(sys.argv) >= 4:
            await _test_source(int(sys.argv[3]))
        else:
            print("用法: python cli.py sources <list|add|remove|test> [args]")

    elif cmd == "scheduler" and len(sys.argv) >= 3:
        sub = sys.argv[2]
        if sub == "status":
            await _scheduler_status()
        elif sub == "on":
            await _scheduler_on()
        elif sub == "off":
            await _scheduler_off()
        else:
            print("用法: python cli.py scheduler <status|on|off>")

    elif cmd == "wechat" and len(sys.argv) >= 3:
        sub = sys.argv[2]
        if sub == "login":
            await _wechat_login()
        elif sub == "upload" and len(sys.argv) >= 4:
            await _wechat_upload(int(sys.argv[3]))
        elif sub == "status":
            await _wechat_status()
        else:
            print("用法: python cli.py wechat <login|upload|status> [article_id]")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
