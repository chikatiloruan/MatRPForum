from config import XF_USER, XF_TFA_TRUST, XF_SESSION, FORUM_BASE
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from .storage import list_all_tracks, update_last
from .utils import detect_type, extract_thread_id, extract_forum_id, normalize_url
from typing import Optional

POLL_INTERVAL = 10  # можно менять через переменную в конфиге, если нужно


class ForumTracker:
    def __init__(self, vkbot):
        self.vk = vkbot
        # trigger для команды /check
        self.vk.set_trigger(lambda: asyncio.get_event_loop().create_task(self.check_all()))
        
        # cookies из config.py
        self.cookies = [
            {"xf_user": XF_USER, "xf_session": XF_SESSION, "xf_tfa_trust": XF_TFA_TRUST},
            {"xf_user": XF_USER, "xf_session": XF_SESSION, "xf_tfa_trust": XF_TFA_TRUST},
            {"xf_user": XF_USER, "xf_session": XF_SESSION, "xf_tfa_trust": XF_TFA_TRUST},
        ]
        self.loop_task = None

    async def start_loop(self):
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
        by_url = {}
        for peer_id, url, typ, last_id in rows:
            by_url.setdefault(url, []).append((peer_id, typ, last_id))

        async with aiohttp.ClientSession() as session:
            tasks = []
            for url, subscribers in by_url.items():
                tasks.append(self._check_url(session, url, subscribers))
            if tasks:
                await asyncio.gather(*tasks)

    async def _fetch_with_all_cookies(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        async def do_req(cookie_set):
            headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
            cookie_header = "; ".join([
                f"xf_user={cookie_set.get('xf_user','')}",
                f"xf_session={cookie_set.get('xf_session','')}",
                f"xf_tfa_trust={cookie_set.get('xf_tfa_trust','')}"
            ])
            try:
                async with session.get(url, headers={**headers, "Cookie": cookie_header}, timeout=30) as resp:
                    text = await resp.text()
                    if resp.status == 200 and text:
                        return text
                    return None
            except Exception:
                return None

        tasks = [asyncio.create_task(do_req(c)) for c in self.cookies]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=25)
        for d in done:
            res = d.result()
            if res:
                for p in pending:
                    p.cancel()
                return res
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

        if typ == "thread":
            posts = soup.select('article.message.message--post')
            parsed = []
            for post in posts:
                post_id = post.get('data-message-id') or post.get('data-content')
                post_link = f"https://forum.matrp.ru/index.php?posts/{post_id.split('-')[-1]}/" if post_id else "N/A"

                author_tag = post.select_one('h4.message-name > a') or post.select_one('span.username')
                author = author_tag.text.strip() if author_tag else "Unknown"

                text_tag = post.select_one('div.bbWrapper')
                text = text_tag.get_text(separator='\n').strip() if text_tag else ""

                date_tag = post.select_one('time')
                date = date_tag.text.strip() if date_tag else "Unknown"

                if text:
                    parsed.append({
                        "id": str(post_id) if post_id else text[:32],
                        "author": author,
                        "text": text,
                        "date": date,
                        "link": post_link
                    })

            if not parsed:
                return

            newest = parsed[-1]  # последний элемент — новый
            for peer_id, _, last_id in subscribers:
                if last_id is None or last_id != newest["id"]:
                    excerpt = newest["text"][:1500]
                    self.vk.send(peer_id,
                                 f"[Новый пост]\nДата: {newest['date']}\nАвтор: {newest['author']}\nТекст: {excerpt}\nСсылка: {newest['link']}")
                    update_last(peer_id, url, newest["id"])

        elif typ == "forum":
            threads = soup.select('div.structItem.structItem--thread')
            parsed = []
            for thread in threads:
                title_tag = thread.select_one('a.structItem-title')
                title = title_tag.text.strip() if title_tag else "No title"

                link_tag = thread.select_one('a[href*="/threads/"]')
                link = "https://forum.matrp.ru" + link_tag['href'] if link_tag else "N/A"

                author_tag = thread.select_one('div.structItem-minor > a.username')
                author = author_tag.text.strip() if author_tag else "Unknown"

                tid = extract_thread_id(link)
                if tid:
                    parsed.append({"id": tid, "title": title, "author": author, "link": link})

            seen = {t["id"]: t for t in parsed}

            for peer_id, _, last_id in subscribers:
                to_send = []
                for tid, t in list(seen.items())[:10]:
                    if last_id is None or tid != last_id:
                        to_send.append(t)
                for t in reversed(to_send):
                    self.vk.send(peer_id,
                                 f"🆕 Новая тема:\nНазвание: {t['title']}\nАвтор: {t['author']}\nСсылка: {t['link']}")
                    update_last(peer_id, url, t['id'])
        else:
            return
