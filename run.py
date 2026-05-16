import sys
import os
import webbrowser
import threading
import time
import uvicorn
from app.config import settings, DATA_DIR
from license_check import check_license_with_exit


def _ensure_data_dirs():
    """Create runtime data directories if they don't exist."""
    for sub in ["", "articles", "images", "wechat", "channel_uploads", "fonts"]:
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


def _open_browser(host: str, port: int, delay: float = 1.5):
    """Open browser after a short delay so the server is ready."""
    def _open():
        time.sleep(delay)
        url = f"http://{host}:{port}"
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


def _free_port(port: int):
    """Kill any process listening on the given port."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], shell=True, text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and f":{port}" in parts[1] and "LISTENING" in parts[3]:
                pid = parts[4]
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, shell=True)
                    print(f"[run.py] Killed old process (PID {pid}) on port {port}")
                except Exception:
                    pass
    except Exception:
        pass


def main():
    check_license_with_exit()
    _ensure_data_dirs()

    # When frozen, change working dir to exe directory
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    # Kill any existing process on the target port
    _free_port(settings.app_port)

    # Import app inside function so frozen hook can set up sys.path first
    from app.main import app

    host = settings.app_host
    port = settings.app_port
    # Use 127.0.0.1 for browser (0.0.0.0 won't resolve in browser)
    browser_host = "127.0.0.1" if host == "0.0.0.0" else host
    _open_browser(browser_host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
