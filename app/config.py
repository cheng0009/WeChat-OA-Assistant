import sys
import os
from pathlib import Path
from pydantic_settings import BaseSettings


# ----- PyInstaller / frozen environment detection -----
def _app_dir() -> Path:
    """Return the directory where the application is installed (resources)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles resources in _MEIPASS
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Return the writable data directory (alongside the exe)."""
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable)) / "data"
    return _app_dir() / "data"


def _env_path() -> str:
    """Return the .env path. Frozen: prefer alongside exe, fall back to bundled."""
    if getattr(sys, "frozen", False):
        exe_env = Path(os.path.dirname(sys.executable)) / ".env"
        if exe_env.exists():
            return str(exe_env)
        # Fall back to bundled template in _internal
        bundled = Path(sys._MEIPASS) / ".env"
        if bundled.exists():
            return str(bundled)
        return str(exe_env)
    return str(_app_dir() / ".env")


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    aihot_api_base: str = "https://aihot.virxact.com"
    aihot_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    schedule_hour: int = 9
    schedule_minute: int = 0
    database_url: str = ""

    image_gen_api_key: str = ""
    image_gen_api_url: str = ""

    model_config = {"env_file": _env_path(), "env_file_encoding": "utf-8"}

    def model_post_init(self, __context):
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{_data_dir() / 'app.db'}"


settings = Settings()
BASE_DIR = _app_dir()
DATA_DIR = _data_dir()
ARTICLES_DIR = DATA_DIR / "articles"
IMAGES_DIR = DATA_DIR / "images"
WECHAT_IMAGES_DIR = DATA_DIR / "wechat"
CHANNEL_UPLOADS_DIR = DATA_DIR / "channel_uploads"
