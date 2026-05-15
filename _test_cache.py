"""Debug the cache_key issue."""
import weakref
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("app/templates"))
loader_key = weakref.ref(env.loader)
name = "article_detail.html"
cache_key = (loader_key, name)
print(f"cache_key type: {type(cache_key)}")
print(f"cache_key hashable: {hasattr(cache_key, '__hash__')}")
try:
    hash(cache_key)
    print("hash() works")
except TypeError as e:
    print(f"hash() fails: {e}")

# Check the LRUCache
print(f"\ncache is None: {env.cache is None}")
print(f"cache type: {type(env.cache)}")
