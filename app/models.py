import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    writer_prompt = Column(Text, default="")
    sticker_prompt = Column(Text, default="")
    schedule_hour = Column(Integer, default=9)
    schedule_minute = Column(Integer, default=0)
    schedule_enabled = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    avatar_image = Column(String(500), default="")
    qrcode_image = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    sources = relationship("Source", back_populates="channel", cascade="all, delete-orphan")
    articles = relationship("Article", back_populates="channel", cascade="all, delete-orphan")
    news_items = relationship("NewsItem", back_populates="channel", cascade="all, delete-orphan")
    daily_logs = relationship("DailyLog", back_populates="channel", cascade="all, delete-orphan")


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    title = Column(String(500), nullable=False)
    viral_title = Column(String(200), default="")
    content = Column(Text, nullable=False)
    sticker_content = Column(Text, default="")
    image_style = Column(String(50), default="deep_blue")
    summary = Column(Text, default="")
    cover_image = Column(String(500), default="")
    wechat_images = Column(Text, default="")
    source_date = Column(String(20), default="")
    status = Column(String(20), default="draft")
    is_daily = Column(Boolean, default=False)
    wechat_draft_url = Column(String(500), default="")
    wechat_media_ids = Column(Text, default="")
    wechat_published = Column(Boolean, default=False)
    wechat_sticker_url = Column(String(500), default="")
    wechat_sticker_published = Column(Boolean, default=False)
    auto_publish_note = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="articles")
    news_items = relationship("NewsItem", back_populates="article", cascade="all, delete-orphan")


class NewsItem(Base):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), default="")
    source = Column(String(200), default="")
    summary = Column(Text, default="")
    content = Column(Text, default="")
    category = Column(String(50), default="")
    published_at = Column(String(50), default="")
    raw_date = Column(String(20), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="news_items")
    article = relationship("Article", back_populates="news_items")


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    date = Column(String(20), nullable=False)
    fetch_count = Column(Integer, default=0)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default="success")
    message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="daily_logs")


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    name = Column(String(100), nullable=False)
    source_type = Column(String(50), nullable=False)
    api_url = Column(String(500), default="")
    api_key = Column(String(200), default="")
    config = Column(Text, default="{}")
    enabled = Column(Boolean, default=True)
    last_fetch_at = Column(DateTime, nullable=True)
    last_fetch_ok = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    channel = relationship("Channel", back_populates="sources")
