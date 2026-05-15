"""Source plugins registry."""
from .base import BaseSource
from .aihot import AIHOTSource
from .rss import RSSSource
from .wechat_sogou import WechatSogouSource
from .html_scraper import HtmlScraperSource
from .weibo_hot import WeiboHotSource
from .v2ex_hot import V2exHotSource
from .zhihu_daily import ZhihuDailySource
from .juejin_hot import JuejinHotSource
from .kr36 import Kr36Source
from .baidu_hot import BaiduHotSource

_PLUGINS: dict[str, type[BaseSource]] = {}


def register_source(plugin_cls: type[BaseSource]):
    _PLUGINS[plugin_cls.type_id] = plugin_cls


def get_source(source_type: str, **kwargs) -> BaseSource:
    cls = _PLUGINS.get(source_type)
    if not cls:
        raise ValueError(f"Unknown source type: {source_type}. Available: {list(_PLUGINS.keys())}")
    return cls(**kwargs)


def get_source_class(source_type: str) -> type[BaseSource]:
    cls = _PLUGINS.get(source_type)
    if not cls:
        raise ValueError(f"Unknown source type: {source_type}")
    return cls


def list_source_types() -> list[dict]:
    return [
        {"type_id": t, "label": cls.label}
        for t, cls in _PLUGINS.items()
    ]


# Register built-in plugins
register_source(AIHOTSource)
register_source(RSSSource)
register_source(WechatSogouSource)
register_source(HtmlScraperSource)
register_source(WeiboHotSource)
register_source(V2exHotSource)
register_source(ZhihuDailySource)
register_source(JuejinHotSource)
register_source(Kr36Source)
register_source(BaiduHotSource)
