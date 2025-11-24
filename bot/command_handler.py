# bot/command_handler.py
import re
import traceback
from .storage import (
    add_track, remove_track, list_tracks,
    add_warn, get_warns, clear_warns,
    add_ban, remove_ban, is_banned
)
from .deepseek_ai import ask_ai
from .permissions import is_admin
from .utils import normalize_url, detect_type, is_forum_domain
from .forum_tracker import fetch_html, parse_thread_posts
import sqlite3
import os

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_data.db")

class CommandHandler:
    def __init__(self, vk):
        self.vk = vk

    def handle(self, text: str, peer_id: int, user_id: int):
        try:
            txt = (text or "").strip()
            if not txt:
                return
            parts = txt.split(maxsplit=1)
            cmd = parts[0].lower()

            # auto-kick if banned
            try:
                if is_banned(peer_id, user_id):
                    if peer_id > 2000000000:
                        chat_id = peer_id - 2000000000
                        try:
                            self.vk.api.messages.removeChatUser(chat_id=chat_id, member_id=user_id)
                        except Exception:
                            pass
                    return
            except Exception:
                pass

            if cmd == "/track":
                return self._cmd_track(peer_id, parts)

            if cmd == "/untrack":
                return self._cmd_untrack(peer_id, parts)

            if cmd == "/list":
                return self._cmd_list(peer_id)

            if cmd == "/check":
                return self._cmd_check(peer_id)

            if cmd == "/checkfa":
                return self._cmd_checkfa(peer_id, parts)

            if cmd == "/ai":
                return self._cmd_ai(peer_id, parts)

            admin_cmds = ("/kick","/ban","/unban","/mute","/unmute","/warn","/warns","/clearwarns","/stats")
            if cmd in admin_cmds and not is_admin(self.vk.api, peer_id, user_id):
                self.vk.send(peer_id, "❌ У вас нет прав для этой команды.")
                return

            if cmd == "/kick":
                return self._cmd_kick(peer_id, parts)

            if cmd == "/ban":
                return self._cmd_ban(peer_id, parts)

            if cmd == "/unban":
                return self._cmd_unban(peer_id, parts)

            if cmd == "/mute":
                return self._cmd_mute(peer_id, parts)

            if cmd == "/unmute":
                return self._cmd_unmute(peer_id, parts)

            if cmd == "/warn":
                return self._cmd_warn(peer_id, parts)

            if cmd == "/warns":
                return self._cmd_warns(peer_id, parts)

            if cmd == "/clearwarns":
                return self._cmd_clearwarns(peer_id, parts)

            if cmd == "/stats":
                return self._cmd_stats(peer_id)

            if cmd == "/help":
                return self._cmd_help(peer_id)

            self.vk.send(peer_id, "Неизвестная команда. Напиши /help")

        except Exception as e:
            self.vk.send(peer_id, "Ошибка обработки команды.")
            traceback.print_exc()

    # --- command implementations ---
    def _cmd_track(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /track <url>")
        url = normalize_url(parts[1])
        from config import FORUM_BASE
        if not is_forum_domain(url, FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Разрешён только форум: {FORUM_BASE}")
        typ = detect_type(url)
        if typ == "unknown":
            typ = "thread"
        # quick fetch to ensure page accessible
        html = fetch_html(url)
        if not html:
            return self.vk.send(peer_id, "❌ Не удалось загрузить страницу. Проверь куки в config.py")
        add_track(peer_id, url, typ)
        self.vk.send(peer_id, f"✅ Отслеживание добавлено: {url}")

    def _cmd_untrack(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /untrack <url>")
        url = normalize_url(parts[1])
        remove_track(peer_id, url)
        self.vk.send(peer_id, "Удалено.")

    def _cmd_list(self, peer_id):
        rows = list_tracks(peer_id)
        if not rows:
            return self.vk.send(peer_id, "Нет отслеживаемых ссылок.")
        lines = [f"{url} ({typ}) last: {last}" for url, typ, last in rows]
        self.vk.send(peer_id, "📌 Отслеживание:\n" + "\n".join(lines))

    def _cmd_check(self, peer_id):
        self.vk.send(peer_id, "Запускаю проверку...")
        ok = self.vk.trigger_check()
        self.vk.send(peer_id, "Готово." if ok else "Ошибка при запуске проверки.")

    def _cmd_checkfa(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /checkfa <url>")
        url = normalize_url(parts[1])
        from config import FORUM_BASE
        if not is_forum_domain(url, FORUM_BASE):
            return self.vk.send(peer_id, "❌ Только forum.matrp.ru")
        html = fetch_html(url)
        if not html:
            return self.vk.send(peer_id, "Не удалось загрузить страницу. Проверь куки.")
        posts = parse_thread_posts(html, url)
        if not posts:
            return self.vk.send(peer_id, "Не найдено сообщений.")
        # send in batches
        batch = []
        for p in posts:
            line = f"👤 {p['author']} • {p['date']}\n{p['text'][:1200]}\n🔗 {p['link']}"
            batch.append(line)
            if len(batch) >= 3:
                self.vk.send_big(peer_id, "\n\n".join(batch))
                batch = []
        if batch:
            self.vk.send_big(peer_id, "\n\n".join(batch))

    def _cmd_ai(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /ai <текст>")
        prompt = parts[1]
        ans = ask_ai(prompt)
        self.vk.send(peer_id, ans)

    # admin implementations
    def _cmd_kick(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /kick <user>")
        if peer_id <= 2000000000:
            return self.vk.send(peer_id, "Kick работает только в беседах.")
        uid = self._parse_user(parts[1])
        try:
            chat_id = peer_id - 2000000000
            self.vk.api.messages.removeChatUser(chat_id=chat_id, member_id=uid)
            self.vk.send(peer_id, f"👢 Выкинут: {uid}")
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка kick: {e}")

    def _cmd_ban(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /ban <user>")
        uid = self._parse_user(parts[1])
        add_ban(peer_id, uid)
        if peer_id > 2000000000:
            try:
                chat = peer_id - 2000000000
                self.vk.api.messages.removeChatUser(chat_id=chat, member_id=uid)
            except:
                pass
        self.vk.send(peer_id, f"🚫 Забанен: {uid}")

    def _cmd_unban(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /unban <user>")
        uid = self._parse_user(parts[1])
        remove_ban(peer_id, uid)
        self.vk.send(peer_id, f"✅ Разбанен: {uid}")

    def _cmd_mute(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /mute <user> <sec>")
        args = parts[1].split()
        uid = self._parse_user(args[0])
        sec = int(args[1]) if len(args) > 1 and args[1].isdigit() else 600
        # VK doesn't provide general mute; simulate
        self.vk.send(peer_id, f"🔇 {uid} замьючен на {sec} сек (симуляция).")

    def _cmd_unmute(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /unmute <user>")
        uid = self._parse_user(parts[1])
        self.vk.send(peer_id, f"🔊 {uid} размьючен (симуляция).")

    def _cmd_warn(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /warn <user>")
        uid = self._parse_user(parts[1])
        add_warn(peer_id, uid)
        cnt = get_warns(peer_id, uid)
        self.vk.send(peer_id, f"⚠️ {uid} предупреждён. Всего: {cnt}")

    def _cmd_warns(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /warns <user>")
        uid = self._parse_user(parts[1])
        cnt = get_warns(peer_id, uid)
        self.vk.send(peer_id, f"Предупреждений у {uid}: {cnt}")

    def _cmd_clearwarns(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /clearwarns <user>")
        uid = self._parse_user(parts[1])
        clear_warns(peer_id, uid)
        self.vk.send(peer_id, f"Предупреждения очищены: {uid}")

    def _cmd_stats(self, peer_id):
        try:
            conn = sqlite3.connect(DB)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tracks")
            total_tracks = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM warns")
            total_warns = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM bans")
            total_bans = cur.fetchone()[0]
            conn.close()
            msg = f"📊 Статистика:\nОтслеживаемых: {total_tracks}\nWarn-строк: {total_warns}\nБаны: {total_bans}"
            self.vk.send(peer_id, msg)
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка stats: {e}")

    def _cmd_help(self, peer_id):
        self.vk.send(peer_id,
            "/track <url>\n/untrack <url>\n/list\n/check\n/checkfa <url>\n"
            "/ai <text>\n/kick <id>\n/ban <id>\n/unban <id>\n/mute <id> <sec>\n/unmute <id>\n"
            "/warn <id>\n/warns <id>\n/clearwarns <id>\n/stats"
        )

    def _parse_user(self, s):
        if not s:
            return 0
        s = s.strip()
        m = re.search(r'id(\d+)', s)
        if m:
            return int(m.group(1))
        m2 = re.search(r'(\d+)', s)
        if m2:
            return int(m2.group(1))
        return 0
