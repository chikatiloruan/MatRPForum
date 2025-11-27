# bot/forum_tracker.py
import threading
import time
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import urljoin
from .utils import (
    normalize_url, detect_type,
    extract_thread_id, extract_post_id_from_article
)
from .storage import list_all_tracks, update_last
import traceback
import logging
import json
import os

# -----------------------
# logger
# -----------------------
LOG_LEVEL = os.environ.get("FORUM_TRACKER_LOG", "INFO").upper()
logger = logging.getLogger("forum_tracker")
if not logger.handlers:
    h = logging.StreamHandler()
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    h.setFormatter(fmt)
    logger.addHandler(h)
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Конфигурация: при импорте берётся из config.py (значения XF_USER, XF_SESSION, XF_TFA_TRUST, FORUM_BASE, POLL_INTERVAL_SEC)
try:
    from config import XF_USER, XF_SESSION, XF_TFA_TRUST, FORUM_BASE, POLL_INTERVAL_SEC
except Exception:
    # если config.py не готов — подставляем заглушки, чтобы модуль импортировался
    XF_USER = ""
    XF_SESSION = ""
    XF_TFA_TRUST = ""
    FORUM_BASE = ""
    POLL_INTERVAL_SEC = 20

DEFAULT_POLL = 20
try:
    POLL = int(POLL_INTERVAL_SEC)
    if POLL <= 0:
        POLL = DEFAULT_POLL
except Exception:
    POLL = DEFAULT_POLL


def build_cookies() -> dict:
    """
    Возвращает словарь cookies для requests, исходя из модульных переменных.
    В старой системе эти переменные могут быть подменены через globals() в __init__.
    """
    return {
        "xf_user": globals().get("XF_USER", XF_USER) or "",
        "xf_session": globals().get("XF_SESSION", XF_SESSION) or "",
        "xf_tfa_trust": globals().get("XF_TFA_TRUST", XF_TFA_TRUST) or "",
    }


def build_cookie_header() -> str:
    c = build_cookies()
    return "; ".join([f"{k}={v}" for k, v in c.items() if v])


def fetch_html(url: str, timeout: int = 15) -> str:
    """
    GET страницу с установленными cookie и базовыми заголовками.
    Возвращает текст страницы или пустую строку при ошибке.
    """
    if not url:
        return ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": FORUM_BASE or ""
    }
    cookies = build_cookies()
    try:
        r = requests.get(url, headers=headers, cookies=cookies, timeout=timeout)
        if r.status_code == 200:
            return r.text
        logger.warning(f"HTTP {r.status_code} for {url}")
        return ""
    except Exception as e:
        logger.exception(f"fetch error for {url}: {e}")
        return ""


def parse_thread_posts(html: str, page_url: str) -> List[Dict]:
    """
    Парсит страницу темы, возвращает список сообщений (словарей).
    Поля: id, author, date, text, link
    """
    soup = BeautifulSoup(html or "", "html.parser")
    # Try xenForo and common selectors
    nodes = soup.select("article.message, article.message--post, .message, .message--post, .message-body")
    if not nodes:
        nodes = soup.select(".post, .postMessage, .messageRow, .message-row")
    out: List[Dict] = []
    for n in nodes:
        try:
            # try to extract id from node HTML or fall back to thread id
            raw = str(n)
            pid = extract_post_id_from_article(raw) or extract_thread_id(page_url) or ""
            # author
            author_el = n.select_one(".message-name a, .username a, .username, .message-userCard a, .message-author, .message-attribution a")
            author = author_el.get_text(strip=True) if author_el else "Неизвестно"
            # date/time
            time_el = n.select_one("time")
            date = ""
            if time_el:
                date = time_el.get("datetime") or time_el.get_text(strip=True) or ""
            else:
                date = n.select_one(".date, .Message-time, .message-time")
                date = date.get_text(strip=True) if date else "Неизвестно"
            # body / текст
            body_el = n.select_one(".bbWrapper, .message-body, .message-content, .postMessage, .uix_post_message")
            text = body_el.get_text("\n", strip=True) if body_el else ""
            link = page_url + (f"#post-{pid}" if pid else "")
            out.append({"id": str(pid or ""), "author": author, "date": date, "text": text, "link": link})
        except Exception as e:
            logger.exception("[forum_tracker] parse_thread_posts item error:")
            continue
    return out


def parse_forum_topics(html: str, page_url: str) -> List[Dict]:
    """
    Парсит страницу раздела форума, возвращает список тем.
    Поля: tid, title, author, url
    """
    soup = BeautifulSoup(html or "", "html.parser")
    items = soup.select(".structItem--thread, .structItem, .discussionListItem, .structItem-title, .threadbit")
    out: List[Dict] = []
    for it in items:
        try:
            a = it.select_one(".structItem-title a, a[href*='/threads/'], a[href*='index.php?threads='], a.thread-title, a.topic-title")
            if not a:
                a = it.select_one("a")
                if not a:
                    continue
            href = a.get("href") or ""
            full = href if href.startswith("http") else urljoin((FORUM_BASE.rstrip("/") + "/"), href.lstrip("/"))
            tid = extract_thread_id(full) or ""
            title = a.get_text(strip=True)
            author_node = it.select_one(".structItem-minor a, .username, .structItem-lastPoster a, .lastPoster, .poster")
            author = author_node.get_text(strip=True) if author_node else "Неизвестно"
            out.append({"tid": str(tid or ""), "title": title, "author": author, "url": full})
        except Exception as e:
            logger.exception("[forum_tracker] parse_forum_topics item error:")
            continue
    return out


class ForumTracker:
    """
    ForumTracker поддерживает два варианта инициализации:
      - ForumTracker(vk)
      - ForumTracker(XF_USER, XF_TFA_TRUST, XF_SESSION, vk)  (старый вызов из main.py)
    """
    def __init__(self, *args):
        # базовые поля
        self.interval = POLL
        self._running = False
        self._worker: Optional[threading.Thread] = None
        self._keepalive_running = True
        self._keepalive_thread: Optional[threading.Thread] = None

        # session for posting (keeps cookies if provided externally)
        self.session = requests.Session()
        # apply cookies from config if present
        ck = build_cookies()
        for k, v in ck.items():
            if v:
                # requests' session.cookies accepts cookiejar or simple set via dict on request;
                # we'll include cookies manually on each request if needed; but adding to session as cookiejar:
                self.session.cookies.set(k, v, domain=None)

        # поддержка двух сигнатур
        if len(args) == 1:
            # ForumTracker(vk)
            self.vk = args[0]
        elif len(args) >= 4:
            # ForumTracker(XF_USER, XF_TFA_TRUST, XF_SESSION, vk)
            xf_user, xf_tfa_trust, xf_session, vk = args[:4]
            # записываем в глобальные переменные модуля, чтобы build_cookies() увидел их
            globals()["XF_USER"] = xf_user
            globals()["XF_TFA_TRUST"] = xf_tfa_trust
            globals()["XF_SESSION"] = xf_session
            # update session cookies
            if xf_user:
                self.session.cookies.set("xf_user", xf_user, domain=None)
            if xf_session:
                self.session.cookies.set("xf_session", xf_session, domain=None)
            if xf_tfa_trust:
                self.session.cookies.set("xf_tfa_trust", xf_tfa_trust, domain=None)
            self.vk = vk
        else:
            raise TypeError("ForumTracker expected (vk) or (XF_USER, XF_TFA_TRUST, XF_SESSION, vk)")

        # регистрируем триггер проверки
        try:
            if self.vk:
                self.vk.set_trigger(self.force_check)
        except Exception:
            pass

        # старт keepalive-потока (поддержание сессии)
        try:
            self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._keepalive_thread.start()
        except Exception as e:
            logger.exception("[forum_tracker] failed to start keepalive thread:")

    # --- API управления ---
    def start(self):
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        logger.info("[forum_tracker] started, poll interval: %s", self.interval)

    def stop(self):
        self._running = False
        self._keepalive_running = False
        logger.info("[forum_tracker] stopped")

    def force_check(self):
        # запустить проверку в фоновом потоке
        threading.Thread(target=self.check_all, daemon=True).start()

    # внутренний цикл
    def _loop(self):
        while self._running:
            try:
                self.check_all()
            except Exception as e:
                logger.exception("[forum_tracker] loop error:")
            time.sleep(self.interval)

    def check_all(self):
        rows = list_all_tracks()
        if not rows:
            return
        # сгруппировать подписки по url
        by_url = {}
        for peer_id, url, typ, last_id in rows:
            by_url.setdefault(url, []).append((peer_id, typ, last_id))
        for url, subs in by_url.items():
            try:
                self._process_url(url, subs)
            except Exception as e:
                logger.exception("[forum_tracker] _process_url error for %s:", url)

    def _process_url(self, url: str, subscribers):
        url = normalize_url(url)
        if not url.startswith(FORUM_BASE):
            logger.debug("[forum_tracker] skipping non-forum url: %s", url)
            return
        html = fetch_html(url)
        if not html:
            logger.debug("[forum_tracker] failed to fetch: %s", url)
            return
        typ = detect_type(url)
        # THREAD: watch posts
        if typ == "thread":
            posts = parse_thread_posts(html, url)
            if not posts:
                return
            newest = posts[-1]
            for peer_id, _, last in subscribers:
                last_str = str(last) if last is not None else None
                if last_str != str(newest["id"]):
                    msg = (
                        f"📝 Новый пост\n👤 {newest['author']}  •  {newest['date']}\n\n"
                        f"{(newest['text'][:1500] + '...') if len(newest['text'])>1500 else newest['text']}\n\n🔗 {newest['link']}"
                    )
                    try:
                        self.vk.send(peer_id, msg)
                    except Exception:
                        logger.exception("[forum_tracker] vk send error:")
                    try:
                        update_last(peer_id, url, str(newest["id"]))
                    except Exception:
                        logger.exception("[forum_tracker] update_last error:")
        # FORUM: watch new topics in section
        elif typ == "forum":
            topics = parse_forum_topics(html, url)
            if not topics:
                return
            latest = topics[-6:]
            for peer_id, _, last in subscribers:
                last_str = str(last) if last is not None else None
                for t in latest:
                    if last_str != str(t["tid"]):
                        msg = f"🆕 Новая тема\n📄 {t['title']}\n👤 {t['author']}\n🔗 {t['url']}"
                        try:
                            self.vk.send(peer_id, msg)
                        except Exception:
                            logger.exception("[forum_tracker] vk send error:")
                        try:
                            update_last(peer_id, url, str(t["tid"]))
                        except Exception:
                            logger.exception("[forum_tracker] update_last error:")
        # MEMBERS: snapshot
        elif typ == "members":
            soup = BeautifulSoup(html, "html.parser")
            users = [a.get_text(strip=True) for a in soup.select(".username, .userTitle, .memberUsername a")[:20]]
            if users:
                s = "👥 Участники (часть): " + ", ".join(users)
                for peer_id, _, _ in subscribers:
                    try:
                        self.vk.send(peer_id, s)
                    except Exception:
                        logger.exception("[forum_tracker] vk send error:")
        else:
            logger.debug("[forum_tracker] unknown type: %s", url)

    def _keepalive_loop(self):
        """
        Периодически пингуем FORUM_BASE, чтобы поддерживать сессию/куки живыми.
        """
        while self._keepalive_running:
            try:
                _ = fetch_html(FORUM_BASE)
            except Exception:
                logger.exception("[forum_tracker] keepalive error:")
            time.sleep(max(60, self.interval * 3))

    # ---------- manual helpers ----------
    def manual_fetch_posts(self, url: str) -> List[Dict]:
        url = normalize_url(url)
        if not url.startswith(FORUM_BASE):
            raise ValueError("URL must start with FORUM_BASE")
        html = fetch_html(url)
        if not html:
            raise RuntimeError("Failed to fetch page (check cookies)")
        return parse_thread_posts(html, url)

    def fetch_latest_post_id(self, url: str) -> Optional[str]:
        url = normalize_url(url)
        html = fetch_html(url)
        if not html:
            return None
        typ = detect_type(url)
        if typ == "thread":
            posts = parse_thread_posts(html, url)
            if posts:
                return str(posts[-1]["id"])
        elif typ == "forum":
            topics = parse_forum_topics(html, url)
            if topics:
                return str(topics[-1]["tid"])
        return None

    # ---------- posting (reply) ----------
    def post_message(self, url: str, message: str) -> Dict:
        """
        Robust XenForo reply poster.

        Strategy:
          1) fetch topic page, find likely reply form/editor
          2) parse hidden inputs and tokens
          3) try ajax/json POST if XF expects JSON
          4) fallback to normal form POST (application/x-www-form-urlencoded)
          5) fallback to multipart/form-data (requests will encode)
          6) verify by fetching topic and searching for a snippet
        Returns dict {"ok": bool, "error": str, "response": str}
        """
        try:
            url = normalize_url(url)
        except Exception:
            logger.exception("normalize_url failed")
            return {"ok": False, "error": "normalize_url error"}

        if not url.startswith(FORUM_BASE):
            logger.debug("post_message: url not on forum base: %s", url)
            return {"ok": False, "error": "URL not on forum base"}

        html = fetch_html(url)
        if not html:
            return {"ok": False, "error": "Cannot fetch topic page (cookies?)"}

        soup = BeautifulSoup(html, "html.parser")

        # --- find editor/form robustly ---
        # Prefer explicit XF editor/form selectors but fall back to generic
        form = (
            soup.select_one("form.message-editor")
            or soup.select_one("form#QuickReplyForm")
            or soup.select_one("form[action*='add-reply']")
            or soup.select_one("form[action*='post']")
            or soup.select_one("form.js-quickReply")
            or soup.select_one("form[data-xf-init*='quick-reply']")
            or soup.select_one("form")
        )

        if not form:
            logger.debug("post_message: reply form not found on page")
            return {"ok": False, "error": "Reply form not found on page"}

        action = form.get("action") or url
        if not action.startswith("http"):
            action = urljoin(FORUM_BASE.rstrip("/") + "/", action.lstrip("/"))

        logger.debug("post_message: action URL = %s", action)

        # collect inputs
        payload_base = {}
        for inp in form.select("input"):
            name = inp.get("name")
            if not name:
                continue
            # prefer explicit value attribute
            payload_base[name] = inp.get("value", "")

        # Try to detect token / csrf
        token_input = soup.find("input", {"name": "_xfToken"}) or soup.find("input", {"name": "_xfToken_"})
        if token_input and token_input.get("value"):
            payload_base.setdefault("_xfToken", token_input.get("value"))

        # also detect meta csrf token
        meta_csrf = soup.find("meta", {"name": "csrf-token"})
        meta_csrf_value = meta_csrf.get("content") if meta_csrf and meta_csrf.get("content") else None

        # find candidate textarea/editor fields
        # Common names: message_html (Froala), message, message_text, message_body, message_plain
        candidates = []
        ta = form.select_one("textarea[name='message_html']") or form.select_one("textarea[data-original-name='message']")
        if ta and ta.get("name"):
            candidates.append(ta.get("name"))
        # include any other textarea name found
        for t in form.select("textarea"):
            n = t.get("name")
            if n and n not in candidates:
                candidates.append(n)

        # standard fallbacks
        for fallback in ["message_html", "message", "message_text", "message_body", "message_plain", "message_raw"]:
            if fallback not in candidates:
                candidates.append(fallback)

        # small helper to verify post by fetching topic and checking snippet presence
        def verify_posted(snippet: str, tries: int = 3, delay: float = 2.0) -> bool:
            if not snippet:
                return True
            for i in range(tries):
                time.sleep(delay)
                try:
                    new_html = fetch_html(url)
                    if new_html and snippet in new_html:
                        return True
                except Exception:
                    logger.debug("verify_posted: exception on fetch verify, try %s", i)
            return False

        snippet = " ".join(message.split()[:6])

        # headers
        headers_common = {
            "User-Agent": "Mozilla/5.0 (compatible; ForumPoster/1.0)",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest"
        }
        if meta_csrf_value:
            headers_common["X-CSRF-Token"] = meta_csrf_value

        session = getattr(self, "session", requests.Session())

        # Ensure session has cookies from build_cookies
        try:
            cks = build_cookies()
            # set cookies on session
            for k, v in cks.items():
                if v:
                    session.cookies.set(k, v, domain=None)
        except Exception:
            logger.debug("failed to set cookies on session")

        last_err = None

        # Try several posting strategies in order: JSON/ajax -> form post -> multipart
        for field_name in candidates:
            logger.debug("post_message: trying field '%s'", field_name)
            try:
                payload = dict(payload_base)  # copy base inputs
                # put message into the candidate field
                if field_name.endswith("html"):
                    payload[field_name] = message  # keep raw html or plain depending on content
                else:
                    payload[field_name] = message

                # include common XF flags to request JSON if supported
                payload.setdefault("_xfWithData", "1")
                payload.setdefault("_xfResponseType", "json")

                # 1) attempt JSON-style POST (some XF endpoints accept json)
                try:
                    headers_json = dict(headers_common)
                    headers_json["Accept"] = "application/json, text/javascript, */*; q=0.01"
                    r = session.post(action, data=payload, headers=headers_json, timeout=25, allow_redirects=True)
                    logger.debug("post_message: POST status %s for field %s", getattr(r, "status_code", None), field_name)
                except Exception as e:
                    logger.debug("post_message: JSON-style post failed for field %s: %s", field_name, e)
                    r = None

                # if server responded OK-ish, try to validate
                if r is not None and getattr(r, "status_code", 0) in (200, 302):
                    text = getattr(r, "text", "") or ""
                    # some XF returns JSON with success:true
                    if ("success" in text.lower()) or ("message" in text.lower()) or r.status_code == 302:
                        # verify appearance on thread
                        if snippet and verify_posted(snippet):
                            logger.info("post_message: posted (via form) using field %s", field_name)
                            return {"ok": True, "response": text[:2000]}
                        # If not visible, still might be queued -> try next fallback
                        last_err = f"Posted but not visible with field {field_name}"
                        logger.debug(last_err)
                        # continue to next strategy for same field: multipart
                    else:
                        # server responded but reported error text
                        last_err = f"Server response not success for field {field_name}: {text[:200]}"
                        logger.debug(last_err)
                else:
                    last_err = f"HTTP {getattr(r, 'status_code', 'no-response')} for field {field_name}"

                # 2) Try multipart/form-data (requests will encode automatically when files param present or when using files)
                try:
                    # no files here — but some servers treat multipart differently; use requests to encode as multipart by using files param with empty placeholder
                    files = {}
                    data = dict(payload)
                    # small trick: put the message in files as well to force multipart (server may accept)
                    files[field_name] = (None, payload.get(field_name, ""))
                    # keep headers minimal; requests will set the multipart boundary
                    r2 = session.post(action, data=data, files=files, headers=headers_common, timeout=25, allow_redirects=True)
                    logger.debug("post_message: multipart POST status %s for field %s", getattr(r2, "status_code", None), field_name)
                    if getattr(r2, "status_code", 0) in (200, 302):
                        text2 = getattr(r2, "text", "") or ""
                        if ("success" in text2.lower()) or ("message" in text2.lower()) or r2.status_code == 302:
                            if snippet and verify_posted(snippet):
                                logger.info("post_message: posted (via multipart) using field %s", field_name)
                                return {"ok": True, "response": text2[:2000]}
                            last_err = f"Multipart posted but not visible for field {field_name}"
                            logger.debug(last_err)
                        else:
                            last_err = f"Multipart response not success for field {field_name}: {text2[:200]}"
                    else:
                        last_err = f"HTTP {getattr(r2, 'status_code', 'no-response')} (multipart) for field {field_name}"
                except Exception as e:
                    logger.debug("post_message: multipart attempt failed for field %s: %s", field_name, e)

                # 3) As a final fallback, try a plain form-encoded POST via requests (already attempted above)
                # already tried data=payload above, so move to next candidate field
            except Exception as e:
                logger.exception("post_message: error while trying field %s:", field_name)
                last_err = str(e)
                continue

        # if we reach here -> all attempts failed
        logger.warning("post_message: all attempts failed. last_err=%s", last_err)
        return {"ok": False, "error": last_err or "Unknown posting error", "response": ""}


def stay_online_loop():
    """
    Запускает простой GET на FORUM_BASE с cookie каждые N секунд.
    Этот поток можно запускать в main.py отдельно:
      threading.Thread(target=stay_online_loop, daemon=True).start()
    """
    cookies = build_cookies()
    url = FORUM_BASE or ""
    if not url:
        logger.warning("[forum_tracker] stay_online_loop: FORUM_BASE not configured")
        return

    while True:
        try:
            requests.get(url, cookies=cookies, timeout=10)
            logger.debug("[ONLINE] Пинг отправлен, аккаунт активен")
        except Exception as e:
            logger.exception("[ONLINE ERROR]")
        time.sleep(180)
