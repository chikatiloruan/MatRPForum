# bot/utils.py
import re
import sys
from urllib.parse import urlparse, parse_qs

def log(msg: str):
    print(f"[UTILS] {msg}", file=sys.stderr)


def normalize_url(url: str) -> str:
    """Нормализует URL, не ломает query и параметры."""
    try:
        if not url:
            return url

        url = url.strip()

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        url = url.replace("\n", "").replace("\r", "")

        if url.endswith("//"):
            url = url[:-1]

        return url
    except Exception as e:
        log(f"normalize_url ERROR: {e}")
        return url


def detect_type(url: str) -> str:
    """Определяет тип ссылки по любому формату XenForo."""
    try:
        if not url:
            return "unknown"

        u = url.lower()

        # любые темы
        if (
            "/threads/" in u or
            "threads=" in u or
            "/posts/" in u
        ):
            return "thread"

        # любые форумы
        if (
            "/forums/" in u or
            "forums=" in u
        ):
            return "forum"

        return "unknown"
    except Exception as e:
        log(f"detect_type ERROR: {e}")
        return "unknown"


def extract_thread_id(url: str) -> str:
    """Извлекает ID темы / поста."""
    try:
        if not url:
            return ""

        m = re.search(r'/posts/(\d+)', url)
        if m:
            return m.group(1)

        m = re.search(r'\.(\d+)(?:/|$)', url)
        if m:
            return m.group(1)

        m = re.search(r'threads=.*?\.([0-9]+)', url)
        if m:
            return m.group(1)

        m = re.search(r'threads=([0-9]+)', url)
        if m:
            return m.group(1)

        return ""
    except Exception as e:
        log(f"extract_thread_id ERROR: {e}")
        return ""


def extract_post_id_from_anchor(node) -> str:
    """Вытаскивает ID поста из HTML-атрибутов."""
    try:
        if not node:
            return ""
        v = node.get("data-message-id") or node.get("data-content") or node.get("id")
        if v:
            m = re.search(r'(\d+)', str(v))
            if m:
                return m.group(1)
        return ""
    except Exception as e:
        log(f"extract_post_id_from_anchor ERROR: {e}")
        return ""
