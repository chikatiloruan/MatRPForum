# bot/forum_tracker.py
import threading
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from .utils import normalize_url, detect_type, extract_thread_id, extract_post_id_from_anchor, is_forum_domain
from .storage import list_all_tracks, update_last
from config import XF_USER, XF_SESSION, XF_TFA_TRUST, FORUM_BASE, POLL_INTERVAL_SEC

DEFAULT_POLL = 20

def build_cookie_header():
    return f"xf_user={XF_USER}; xf_session={XF_SESSION}; xf_tfa_trust={XF_TFA_TRUST}"

def fetch_html(url: str, timeout: int = 15) -> Optional[str]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ForumTracker/1.0)", "Cookie": build_cookie_header()}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.text
        print(f"[TRACKER] HTTP {r.status_code} for {url}")
        return None
    except Exception as e:
        print(f"[TRACKER] fetch error {e} for {url}")
        return None

def parse_thread_posts(html: str, page_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    posts_nodes = soup.select("article.message, article.message--post, .message")
    if not posts_nodes:
        posts_nodes = soup.select(".message--post, .message-body")
    out = []
    for node in posts_nodes:
        pid = extract_post_id_from_anchor(node) or extract_thread_id(page_url)
        author_el = node.select_one(".message-name a, .username, .message-userCard a, .message-userDetails a")
        author = author_el.get_text(strip=True) if author_el else "Неизвестно"
        time_el = node.select_one("time")
        date = time_el.get("datetime") if time_el and time_el.get("datetime") else (time_el.get_text(strip=True) if time_el else "Неизвестно")
        body_el = node.select_one(".bbWrapper, .message-body, .message-content")
        text = body_el.get_text("\n", strip=True) if body_el else ""
        link = page_url + (f"#post-{pid}" if pid else "")
        out.append({"id": pid or "", "author": author, "date": date, "text": text, "link": link})
    return out

def parse_forum_topics(html: str, page_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(".structItem--thread, .structItem")
    out = []
    for it in nodes:
        a = it.select_one(".structItem-title a, a[href*='/threads/'], a[href*='index.php?threads=']")
        if not a:
            continue
        href = a.get("href") or ""
        full = href if href.startswith("http") else (FORUM_BASE.rstrip("/") + href)
        tid = extract_thread_id(full)
        title = a.get_text(strip=True)
        author_node = it.select_one(".structItem-minor a, .structItem-parts a, .username")
        author = author_node.get_text(strip=True) if author_node else "Неизвестно"
        out.append({"tid": tid or "", "title": title, "author": author, "url": full})
    return out

class ForumTracker:
    def __init__(self, vk):
        self.vk = vk
        self.interval = int(POLL_INTERVAL_SEC or DEFAULT_POLL)
        self.running = False
        self._thread = None
        self.vk.set_trigger(self.force_check)

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[TRACKER] started")

    def stop(self):
        self.running = False
        print("[TRACKER] stopping")

    def force_check(self):
        t = threading.Thread(target=self.check_all, daemon=True)
        t.start()

    def _loop(self):
        while self.running:
            try:
                self.check_all()
            except Exception as e:
                print("[TRACKER] loop error:", e)
            time.sleep(self.interval)

    def check_all(self):
        rows = list_all_tracks()
        if not rows:
            return
        by_url = {}
        for peer_id, url, typ, last in rows:
            by_url.setdefault(url, []).append((peer_id, typ, last))
        for url, subs in by_url.items():
            self._process_url(url, subs)

    def _process_url(self, url: str, subscribers):
        url = normalize_url(url)
        if not is_forum_domain(url, FORUM_BASE):
            print(f"[TRACKER] skip non-forum domain: {url}")
            return
        html = fetch_html(url)
        if not html:
            print(f"[TRACKER] failed to fetch: {url}")
            return
        typ = detect_type(url)
        if typ == "thread":
            posts = parse_thread_posts(html, url)
            if not posts:
                return
            newest = posts[-1]
            for peer_id, _, last in subscribers:
                if last is None or str(last) != str(newest["id"]):
                    msg = f"📝 Новый пост\n👤 {newest['author']}  •  {newest['date']}\n\n{newest['text'][:1500]}\n\n🔗 {newest['link']}"
                    try:
                        self.vk.send(peer_id, msg)
                    except Exception as e:
                        print("[TRACKER] vk send error:", e)
                    update_last(peer_id, url, str(newest['id']))
        elif typ == "forum":
            topics = parse_forum_topics(html, url)
            if not topics:
                return
            # send a few newest
            latest = topics[-6:]
            for peer_id, _, last in subscribers:
                for t in latest:
                    if last is None or str(t['tid']) != str(last):
                        msg = f"🆕 Новая тема\n📄 {t['title']}\n👤 {t['author']}\n🔗 {t['url']}"
                        try:
                            self.vk.send(peer_id, msg)
                        except Exception as e:
                            print("[TRACKER] vk send error:", e)
                        update_last(peer_id, url, str(t['tid']))

    # manual check for /checkfa
    def manual_check(self, url: str) -> List[Dict]:
        url = normalize_url(url)
        if not is_forum_domain(url, FORUM_BASE):
            raise ValueError("URL must be on forum.matrp.ru")
        html = fetch_html(url)
        if not html:
            raise RuntimeError("Failed to fetch page (check cookies)")
        return parse_thread_posts(html, url)
