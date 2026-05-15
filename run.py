import sys
import os
import uvicorn
from app.config import settings, DATA_DIR
from license_check import check_license_with_exit


def _ensure_data_dirs():
    """Create runtime data directories if they don't exist."""
    for sub in ["", "articles", "images", "wechat", "channel_uploads", "fonts"]:
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


def main():
    check_license_with_exit()
    _ensure_data_dirs()

    # When frozen, change working dir to exe directory
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    # Import app inside function so frozen hook can set up sys.path first
    from app.main import app

    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
