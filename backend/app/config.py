import os
import socket
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _sync_system_proxy() -> None:
    """把 Windows 系统代理（注册表）同步到环境变量，供 httpx / websockets 使用。

    requests 会自动读注册表代理，但 httpx 只认环境变量。仅当代理端口当前
    可达时才启用，避免系统代理残留（代理软件未运行）导致所有请求失败。
    """
    if os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY"):
        return
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return
    for scheme in ("https", "http"):
        url = proxies.get(scheme)
        if not url or not url.startswith("http"):
            continue
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=1):
                os.environ.setdefault("HTTP_PROXY", url)
                os.environ.setdefault("HTTPS_PROXY", url)
                return
        except OSError:
            continue


_sync_system_proxy()

BINANCE_BASE = os.getenv("BINANCE_BASE", "https://api.binance.com")
BINANCE_WS = os.getenv("BINANCE_WS", "wss://stream.binance.com:9443")
REALTIME_WS_ENABLED = os.getenv("REALTIME_WS_ENABLED", "1") == "1"
