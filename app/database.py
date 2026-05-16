import os
import sqlite3
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text

from app.config import settings

# Derive file path for synchronous sqlite3 access (used in column-type fix)
_DB_FILE = settings.database_url.replace("sqlite+aiosqlite:///", "")

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _fix_boolean_column_types():
    """Rebuild articles table if wechat_published / wechat_sticker_published
    are TEXT columns (legacy bug).  Called synchronously during init_db."""
    if not os.path.exists(_DB_FILE):
        return
    conn = sqlite3.connect(_DB_FILE)
    try:
        cur = conn.execute("PRAGMA table_info(articles)")
        col_types = {r[1]: r[2].upper() for r in cur.fetchall()}
        wp = col_types.get("wechat_published", "")
        wsp = col_types.get("wechat_sticker_published", "")
        if wp == "INTEGER" and wsp == "INTEGER":
            return  # already correct

        print("[DB] Fixing boolean column types (TEXT -> INTEGER) …")
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='articles'")
        old_sql = cur.fetchone()[0]
        new_sql = old_sql.replace(
            "wechat_published TEXT DEFAULT ''",
            "wechat_published INTEGER DEFAULT 0"
        ).replace(
            "wechat_sticker_published TEXT DEFAULT ''",
            "wechat_sticker_published INTEGER DEFAULT 0"
        )
        conn.execute(new_sql.replace("CREATE TABLE articles", "CREATE TABLE articles_new"))

        cur = conn.execute("PRAGMA table_info(articles)")
        cols = [r[1] for r in cur.fetchall()]
        col_list = ", ".join(cols)
        placeholders = ", ".join(f":{c}" for c in cols)

        cur = conn.execute(f"SELECT {col_list} FROM articles")
        rows = cur.fetchall()
        for row in rows:
            vals = dict(zip(cols, row))
            for cname in ("wechat_published", "wechat_sticker_published"):
                v = vals[cname]
                vals[cname] = 0 if v in ("0", "", 0, None) else 1
            conn.execute(f"INSERT INTO articles_new ({col_list}) VALUES ({placeholders})", vals)

        conn.execute("DROP TABLE articles")
        conn.execute("ALTER TABLE articles_new RENAME TO articles")
        conn.commit()
        print("[DB] Boolean columns fixed: TEXT -> INTEGER")
    except Exception as exc:
        print(f"[DB] Boolean column fix error (non-fatal): {exc}")
    finally:
        conn.close()


async def init_db():
    from app.models import Article, NewsItem, DailyLog, Source, Channel, WritingSkill
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Helper to add column if missing (SQLite-safe)
    async def _add_col(table: str, col_def: str):
        try:
            async with engine.begin() as c:
                await c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                print(f"[DB] Added column to {table}: {col_def.split()[0]}")
        except Exception:
            pass

    # Add channel_id to existing tables
    for tbl in ["articles", "news_items", "sources", "daily_logs"]:
        await _add_col(tbl, "channel_id INTEGER DEFAULT NULL")

    # Add content to news_items
    await _add_col("news_items", "content TEXT DEFAULT ''")

    # Legacy migrations (articles table) — TEXT columns
    for col in ["sticker_content", "image_style", "wechat_draft_url", "wechat_media_ids",
                 "wechat_sticker_url", "auto_publish_note"]:
        await _add_col("articles", f"{col} TEXT DEFAULT ''")

    # Legacy migrations (articles table) — BOOLEAN columns (use INTEGER for SQLite)
    for col in ["wechat_published", "wechat_sticker_published"]:
        await _add_col("articles", f"{col} INTEGER DEFAULT 0")

    # Sync column-type fix (TEXT -> INTEGER) for DBs created before the schema change
    _fix_boolean_column_types()

    # Fix old TEXT-based booleans (stored as '0'/'1' strings)
    try:
        async with engine.begin() as c:
            await c.execute(text(
                "UPDATE articles SET wechat_published=0 WHERE wechat_published='0'"
            ))
            await c.execute(text(
                "UPDATE articles SET wechat_sticker_published=0 WHERE wechat_sticker_published='0'"
            ))
    except Exception:
        pass

    # Channel avatar / qrcode
    for col in ["avatar_image", "qrcode_image"]:
        await _add_col("channels", f"{col} TEXT DEFAULT ''")

    # writing_skill_id on channels
    await _add_col("channels", "writing_skill_id INTEGER DEFAULT NULL")

    # WritingSkill columns (may already exist from create_all)
    await _add_col("writing_skills", "style_guide TEXT DEFAULT ''")
    await _add_col("writing_skills", "quality_checklist TEXT DEFAULT ''")

    # Article.enhanced
    await _add_col("articles", "enhanced INTEGER DEFAULT 0")

    # Seed / update preset skills
    await _seed_preset_skills()


async def _seed_preset_skills():
    """Insert or update built-in writing skills."""
    from app.models import WritingSkill
    from app.writing_skills import PRESET_SKILL_DEFS, LAOCHENG_STYLE_GUIDE, LAOCHENG_QUALITY_CHECKLIST

    async with async_session() as session:
        preset_name = PRESET_SKILL_DEFS[0].name if PRESET_SKILL_DEFS else "老成写作"
        result = await session.execute(
            select(WritingSkill).where(WritingSkill.name == preset_name).limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing preset with new fields if missing
            if not existing.style_guide:
                existing.style_guide = LAOCHENG_STYLE_GUIDE
            if not existing.quality_checklist:
                existing.quality_checklist = LAOCHENG_QUALITY_CHECKLIST
            updated = any([not existing.style_guide, not existing.quality_checklist])
            if updated:
                await session.commit()
                print(f"[DB] Updated preset skill '{preset_name}' with style guide & checklist")
            return

        for defn in PRESET_SKILL_DEFS:
            skill = WritingSkill(
                is_preset=True,
                name=defn.name,
                description=defn.description,
                persona=defn.persona,
                system_prompt=defn.system_prompt,
                sticker_prompt=defn.sticker_prompt,
                style_guide=defn.style_guide,
                quality_checklist=defn.quality_checklist,
            )
            session.add(skill)
        await session.commit()
        print(f"[DB] Seeded {len(PRESET_SKILL_DEFS)} preset writing skill(s)")


async def get_db():
    async with async_session() as session:
        yield session
