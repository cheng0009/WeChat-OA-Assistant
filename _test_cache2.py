"""Debug the exact Environment configuration."""
from starlette.templating import Jinja2Templates

templates = Jinja2Templates("app/templates")
env = templates.env
print(f"env.cache type: {type(env.cache)}")
print(f"env.cache: {env.cache}")
print(f"env.auto_reload: {env.auto_reload}")

# Check the loader
print(f"env.loader: {env.loader}")
print(f"env.loader type: {type(env.loader)}")

# Monkeypatch to debug
original_get = env.cache.get
def debug_get(key):
    print(f"DEBUG cache.get: key type={type(key)}, key={key!r:.100}")
    return original_get(key)

env.cache.get = debug_get

# Now try to get a template
try:
    t = env.get_template("article_detail.html")
    print("Template loaded OK")
except Exception as e:
    import traceback
    traceback.print_exc()
