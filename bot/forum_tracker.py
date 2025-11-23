# bot/forum_tracker.py
import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional
from .storage import list_all_tracks, update_last
from .utils import detect_type, extract_thread_id, normalize_url, extract_post_id_from_anchor
from .config import FORUM_BASE  # if you have FORUM_BASE in config.py
from config import XF_USER, XF_SESSION, XF_TFA_TRUST  # if config at project root
import time

# Poll interval fallback
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SEC", "10"))

# If cookies are provided in config.py, use them; otherwise try env
def _get_cookie_sets():
    # allow three identical sets (if user put only one set)
    c1 = {"xf_user": XF_USER, "xf_session": XF_SESSION, "xf_tfa_trust": XF_TFA_TRUST}
    return [c1, c1, c1]

class ForumTracker:
    def __init__(self, vkbot):
        self.vk = vkbot
        self.vk.set_trigger(lambda: asyncio.get_event_loop().create_task(self.check_all()))
        self.cookies = _get_cookie_sets()

    async def start_loop(self):
        # starts monitoring loop (create task externally)
        await asyncio.create_task(self.check_loop())

    async def check_loop(self):
        while True:
            try:
                await self.check_all()
            except Exception as e:
                print("Tracker loop error:", e)
            await asyncio.sleep(POLL_INTERVAL)

    async def check_all(self):
        rows = list_all_tracks()
        if not rows:
            return
        by_url = {}
        for peer_id, url, typ, last_id in rows:
            by_url.setdefault(url, []).append((peer_id, typ, last_id))

        async with aiohttp.ClientSession() as session:
            tasks = [self._check_url(session, url, subscribers) for url, subscribers in by_url.items()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_with_all_cookies(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """
        Отправляем параллельно 3 запроса с разными наборами cookie и возвращаем первый успешный HTML.
        """
        async def do_req(cookie_set):
            headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
            cookie_header = "; ".join([
                f"xf_user={cookie_set.get('xf_user','')}",
                f"xf_session={cookie_set.get('xf_session','')}",
                f"xf_tfa_trust={cookie_set.get('xf_tfa_trust','')}"
            ])
            try:
                async with session.get(url, headers={**headers, "Cookie": cookie_header}, timeout=25) as resp:
                    if resp.status == 200:
                        return await resp.text()
            except Exception:
                return None
            return None

        tasks = [asyncio.create_task(do_req(c)) for c in self.cookies]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=25)

        # first successful
        for d in done:
            try:
                r = d.result()
                if r:
                    for p in pending:
                        p.cancel()
                    return r
            except Exception:
                pass

        # fallback: wait remaining
        for p in pending:
            try:
                r = await p
                if r:
                    return r
            except Exception:
                pass
        return None

    async def _check_url(self, session: aiohttp.ClientSession, url: str, subscribers):
        url = normalize_url(url)
        typ = detect_type(url)
        html = await self._fetch_with_all_cookies(session, url)
        if not html:
            print("Failed to fetch:", url)
            return

        soup = BeautifulSoup(html, "html.parser")

        # THREAD parsing (новое сообщение в теме)
        if typ == "thread":
            # Try to find message articles (XenForo)
            posts = soup.select("article.message, article.message--post, article.message--post.js-post")
            if not posts:
                # alternative: older markup
                posts = soup.select(".message")

            if not posts:
                return

            newest = posts[-1]
            # post id
            post_id = extract_post_id_from_anchor(newest) or extract_thread_id(url)  # fallback to thread id
            # author
            author_node = newest.select_one(".message-name a, .username, .message-userCard a")
            author = author_node.get_text(strip=True) if author_node else "Неизвестно"
            # date
            date_node = newest.select_one("time, .u-dt")
            date = date_node.get("datetime") if date_node and date_node.get("datetime") else (date_node.get_text(strip=True) if date_node else "?")
            # text
            body_node = newest.select_one(".bbWrapper, .message-body, .message-content, .message-inner .message-content")
            text = body_node.get_text("\n", strip=True) if body_node else "(нет текста)"
            # link to post (try to use post id)
            if post_id:
                # if the forum provides anchor format /posts/<id> or #post-<id>
                link = url
                if not url.endswith("/"):
                    link = url + "/"
                # construct anchor if known
                link_to_post = f"{url}#post-{post_id}" if post_id else url
            else:
                link_to_post = url

            # notify subscribers
            for peer_id, _, last_id in subscribers:
                if last_id is None or str(last_id) != str(post_id):
                    msg = (
                        f"📝 Новый пост в теме\n"
                        f"📅 {date}\n"
                        f"👤 {author}\n\n"
                        f"{text[:1500]}\n\n"
                        f"🔗 {link_to_post}"
                    )
                    try:
                        self.vk.send(peer_id, msg)
                    except Exception as e:
                        print("VK send error:", e)
                    update_last(peer_id, url, str(post_id))
            return

        # FORUM parsing (новая тема в разделе)
        if typ == "forum":
            # thread list items
            # selectors observed on MatRP: .structItem--thread , .structItem
            items = soup.select(".structItem--thread, .structItem")
            threads = []
            for it in items:
                # title/link
                link_node = it.select_one(".structItem-title a, a[href*='/threads/'], a[href*='index.php?threads=']")
                if not link_node:
                    continue
                href = link_node.get("href") or ""
                full = href if href.startswith("http") else (FORUM_BASE.rstrip("/") + href)
                tid = extract_thread_id(full)
                title = link_node.get_text(strip=True)
                # author: can be in .structItem-minor or .username
                author_node = it.select_one(".structItem-minor a, .structItem-parts a, .username")
                author = author_node.get_text(strip=True) if author_node else "Неизвестно"

                if tid:
                    threads.append({"tid": tid, "title": title, "author": author, "url": full})
            if not threads:
                return

            # Sort by id numeric ascending (older -> newer)
            try:
                threads_sorted = sorted(threads, key=lambda x: int(x["tid"]))
            except Exception:
                threads_sorted = threads

            for peer_id, _, last_id in subscribers:
                # send threads that are "newer" than last_id
                # if last_id is None -> send first few latest (we will send newest ones)
                # We'll send items whose tid != last_id and that appear after last_id
                sent_any = False
                for th in threads_sorted[-8:]:  # check last up to 8 threads to avoid spamming
                    if last_id is None or str(th["tid"]) != str(last_id):
                        msg = (
                            f"🆕 Новая тема\n"
                            f"📄 {th['title']}\n"
                            f"👤 Автор: {th['author']}\n"
                            f"🔗 {th['url']}"
                        )
                        try:
                            self.vk.send(peer_id, msg)
                        except Exception as e:
                            print("VK send error:", e)
                        update_last(peer_id, url, th["tid"])
                        sent_any = True
                # if nothing was sent we do nothing
            return

        # unknown type — ignore
        return
