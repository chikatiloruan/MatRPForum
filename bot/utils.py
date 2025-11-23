# bot/utils.py
import re
from urllib.parse import urlparse, parse_qs

def normalize_url(url: str) -> str:
    if not url:
        return url
    url = url.strip()

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    url = url.replace("\n", "").replace("\r", "")

    if url.endswith("//"):
        url = url[:-1]

    print(f"[utils] normalize_url → {url}")
    return url


def detect_type(url: str) -> str:
    if not url:
        return "unknown"

    u = url.lower()
    print(f"[utils] detect_type() check → {u}")

    # THREAD formats
    if (
        "/threads/" in u
        or "index.php?threads=" in u
        or "/posts/" in u
        or re.search(r'threads=.*?\.\d+', u)
    ):
        print("[utils] detect_type = thread")
        return "thread"

    # FORUM formats
    if "/forums/" in u or "index.php?forums=" in u:
        print("[utils] detect_type = forum")
        return "forum"

    print("[utils] detect_type = unknown")
    return "unknown"


def extract_thread_id(url: str) -> str:
    if not url:
        return ""

    print(f"[utils] extract_thread_id from → {url}")

    # /posts/123456/
    m = re.search(r'/posts/(\d+)', url)
    if m:
        print(f"[utils] found post-id: {m.group(1)}")
        return m.group(1)

    # slug.3717567/
    m = re.search(r'\.(\d+)(?:/|$)', url)
    if m:
        print(f"[utils] found .ID: {m.group(1)}")
        return m.group(1)

    # threads=slug.3717567
    m = re.search(r'threads=.*?\.(\d+)', url)
    if m:
        print(f"[utils] found threads=.ID: {m.group(1)}")
        return m.group(1)

    # threads=3717567
    m = re.search(r'threads=(\d+)', url)
    if m:
        print(f"[utils] found threads=ID: {m.group(1)}")
        return m.group(1)

    print("[utils] no thread id found")
    return ""


def extract_post_id_from_anchor(node) -> str:
    if not node:
        return ""
    v = node.get("data-message-id") or node.get("data-content") or node.get("id")
    if v:
        m = re.search(r'(\d+)', str(v))
        if m:
            print(f"[utils] anchor ID: {m.group(1)}")
            return m.group(1)
    return ""
