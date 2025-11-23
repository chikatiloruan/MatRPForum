# bot/utils.py
import re
from urllib.parse import urlparse, parse_qs
import traceback
import sys


# ============================================================
#  УТИЛИТА ДЛЯ ЛОГОВ
# ============================================================
def log_error(context: str, error: Exception):
    """
    Печатает ошибку в консоль красным цветом.
    """
    print("\033[91m[ERROR]", context)
    print("→", error)
    traceback.print_exc()
    print("\033[0m")  # reset color


# ============================================================
#  NORMALIZE URL
# ============================================================
def normalize_url(url: str) -> str:
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
        log_error("normalize_url()", e)
        return url


# ============================================================
#  DETECT TYPE
# ============================================================
def detect_type(url: str) -> str:
    try:
        if not url:
            return "unknown"

        u = url.lower()

        if "/threads/" in u or "index.php?threads=" in u or "/posts/" in u:
            return "thread"

        if "/forums/" in u or "index.php?forums=" in u:
            return "forum"

        return "unknown"

    except Exception as e:
        log_error("detect_type()", e)
        return "unknown"


# ============================================================
#  EXTRACT THREAD ID
# ============================================================
def extract_thread_id(url: str) -> str:
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
        log_error("extract_thread_id()", e)
        return ""


# ============================================================
#  EXTRACT FORUM ID
# ============================================================
def extract_forum_id(url: str) -> str:
    try:
        if not url:
            return ""

        m = re.search(r'forums/.*?\.(\d+)', url)
        if m:
            return m.group(1)

        m = re.search(r'forums=([0-9]+)', url)
        if m:
            return m.group(1)

        return ""

    except Exception as e:
        log_error("extract_forum_id()", e)
        return ""


# ============================================================
#  EXTRACT POST ID FROM HTML NODE
# ============================================================
def extract_post_id_from_anchor(node) -> str:
    try:
        if not node:
            return ""

        v = (
            node.get("data-message-id") or
            node.get("data-content") or
            node.get("id")
        )

        if v:
            m = re.search(r'(\d+)', str(v))
            if m:
                return m.group(1)

        return ""

    except Exception as e:
        log_error("extract_post_id_from_anchor()", e)
        return ""

