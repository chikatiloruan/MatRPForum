
from __future__ import annotations

import re
import traceback
import sqlite3
import os
import json
from typing import List, Tuple, Optional, Dict

# локальные импорты
from .storage import (
    add_track, remove_track, list_tracks,
    add_warn, get_warns, clear_warns,
    add_ban, remove_ban, is_banned, update_last
)
from .deepseek_ai import ask_ai
from .permissions import is_admin
from .utils import normalize_url, detect_type, parse_profile
from .forum_tracker import ForumTracker, parse_forum_topics
from config import FORUM_BASE

# путь к БД (для stats)
DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_data.db")

# папка для JSON шаблонов
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TEMPLATES_FILE = os.path.join(TEMPLATES_DIR, "templates.json")

REACTIONS = {
    "👍 Нравится": 1,
    "❤️ Люблю": 2,
    "😂 XaXa": 3,
    "👋 Bay": 4,
    "😢 Грустно": 5,
    "😡 Злой": 6,
    "🔥 Крутой": 7,
    "✨ Шикарно": 8,
    "😘 Целую": 9,
    "🏆 Лучший": 10
}

OFFLINE_PUNISH_URL = "https://forum.matrp.ru/index.php?threads/28-vydaca-offline-nakazanij-4-urovni.1374310/"
PREFIX_CHANGE_URL = "https://forum.matrp.ru/index.php?threads/28-zaavlenie-na-izmenenie-prefiksa-v-zalobah.1374303/"
FAST_DATA_DIR = "data"
ADMIN_PREFIX = "/ Obama"



# ----------------- Утилиты шаблонов (JSON) -----------------
def _ensure_templates_file():
    if not os.path.exists(TEMPLATES_DIR):
        try:
            os.makedirs(TEMPLATES_DIR, exist_ok=True)
        except Exception:
            pass
    if not os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def load_templates() -> Dict[str, Dict[str, str]]:
    _ensure_templates_file()
    try:
        with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_templates(data: Dict[str, Dict[str, str]]) -> bool:
    _ensure_templates_file()
    try:
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_template_for_peer(peer_id: int, name: str, text: str) -> bool:
    data = load_templates()
    key = str(peer_id)
    if key not in data:
        data[key] = {}
    data[key][name] = text
    return save_templates(data)


def remove_template_for_peer(peer_id: int, name: str) -> bool:
    data = load_templates()
    key = str(peer_id)
    if key in data and name in data[key]:
        del data[key][name]
        # если пусто — удалить ключ
        if not data[key]:
            del data[key]
        return save_templates(data)
    return False


def get_template(peer_id: int, name: str) -> Optional[str]:
    data = load_templates()
    key = str(peer_id)
    if key in data:
        return data[key].get(name)
    return None


def list_templates(peer_id: int) -> List[str]:
    data = load_templates()
    key = str(peer_id)
    if key in data:
        return list(data[key].keys())
    return []



class CommandHandler:
    def __init__(self, vk):
        self.vk = vk

        try:
            # основной корректный запуск трекера
            self.tracker = ForumTracker(vk)
        except Exception as e:
            print(f"[TRACKER INIT ERROR] {e}")
            # если не удалось — не создаём трекер вообще
            self.tracker = None

        self._last_msg = None

  
    def handle(self, text: str, peer_id: int, user_id: int):
        try:
            txt = (text or "").strip()
            if not txt:
                return

            # анти-дубль
            last = self._last_msg
            cur = f"{peer_id}:{user_id}:{txt}"
            if last == cur:
                return
            self._last_msg = cur

            parts = txt.split(maxsplit=2)
            cmd = parts[0].lower()

            # авто-кик при бане
            try:
                if is_banned(peer_id, user_id):
                    if peer_id > 2000000000 and hasattr(self.vk, 'api'):
                        try:
                            chat_id = peer_id - 2000000000
                            self.vk.api.messages.removeChatUser(chat_id=chat_id, member_id=user_id)
                        except Exception:
                            pass
                    return
            except Exception:
                pass

            # --- команды ---
            if cmd == "/track":
                return self.cmd_track(peer_id, parts)

            if cmd == "/debugtopics":
                return self.cmd_debugtopics(peer_id, parts)

            if cmd == "/debugcheck":
                return self.cmd_debugcheck(peer_id, parts)


            if cmd == "/untrack":
                return self.cmd_untrack(peer_id, parts)
            if cmd == "/list":
                return self.cmd_list(peer_id)
            if cmd == "/check":
                return self.cmd_check(peer_id)
            if cmd == "/checkfa":
                return self.cmd_checkfa(peer_id, parts)
            if cmd == "/ai":
                return self.cmd_ai(peer_id, parts)
            if cmd == "/otvet":
                return self.cmd_otvet(peer_id, parts)
            if cmd == "/debug_otvet":
                return self.cmd_debug_otvet(peer_id, parts)
            if cmd == "/debug_forum":
                return self.cmd_debug_forum(peer_id, parts)
            if cmd == "/tlist":
                return self.cmd_tlist(peer_id, parts)
            if cmd == "/tlistall":
                return self.cmd_tlistall(peer_id, parts)
            if cmd == "/checkcookies":
                return self.cmd_checkcookies(peer_id)

            if cmd == "/reaction":
                return self.cmd_reaction(peer_id, parts)
                

            # шаблоны
            if cmd == "/addsh":
                return self.cmd_addsh(peer_id, parts)
            if cmd == "/removesh":
                return self.cmd_removesh(peer_id, parts)
            if cmd == "/shablon":
                return self.cmd_shablon(peer_id, parts)

            # профили
            if cmd == "/profile":
                return self.cmd_profile(peer_id, parts)
            if cmd == "/checkpr":
                return self.cmd_checkpr(peer_id, parts)

            # --- админ команды ---
            admin_cmds = (
                "/kick", "/ban", "/unban", "/mute", "/unmute",
                "/warn", "/warns", "/clearwarns", "/stats"
            )
            if cmd in admin_cmds and not is_admin(getattr(self.vk, 'api', None), peer_id, user_id):
                self.vk.send(peer_id, "❌ У вас нет прав для этой команды.")
                return

            if cmd == "/kick": return self.cmd_kick(peer_id, parts)
            if cmd == "/ban": return self.cmd_ban(peer_id, parts)
            if cmd == "/unban": return self.cmd_unban(peer_id, parts)
            if cmd == "/mute": return self.cmd_mute(peer_id, parts)
            if cmd == "/unmute": return self.cmd_unmute(peer_id, parts)
            if cmd == "/warn": return self.cmd_warn(peer_id, parts)
            if cmd == "/warns": return self.cmd_warns(peer_id, parts)
            if cmd == "/clearwarns": return self.cmd_clearwarns(peer_id, parts)
            if cmd == "/stats": return self.cmd_stats(peer_id)
            if cmd == "/help": return self.cmd_help(peer_id)

            
            self.vk.send(peer_id, "Неизвестная команда. Напиши /help")

        except Exception as e:
            try:
                self.vk.send(peer_id, f"Ошибка: {e}")
            except Exception:
                pass
            traceback.print_exc()

   
    def cmd_debug_otvet(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /debug_otvet <url>")
        url = normalize_url(parts[1])
        try:
            res = self.tracker.debug_reply_form(url)
        except Exception as e:
            return self.vk.send(peer_id, f"❌ Ошибка debug: {e}")
        self._send_long(peer_id, res)

    def cmd_checkcookies(self, peer_id):
        try:
            r = self.tracker.check_cookies()
        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка check_cookies: {e}")
        msg = (
            "🔍 Проверка cookies\n"
            f"Статус: {r.get('status')}\n"
            f"Авторизация: {r.get('logged_in')}\n\n"
            f"Cookies:\n{r.get('cookies_sent')}\n\n"
            f"HTML:\n{r.get('html_sample')}"
        )
        self.vk.send(peer_id, msg)

    def cmd_debug_forum(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /debug_forum <url>")
        url = normalize_url(parts[1])
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Только {FORUM_BASE}")
        try:
            res = self.tracker.debug_forum(url)
        except Exception as e:
            return self.vk.send(peer_id, f"❌ Ошибка debug_forum: {e}")
        self._send_long(peer_id, res)


    def cmd_track(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /track <url>")

        url = normalize_url(parts[1])

        # Проверяем что ссылка относится к форуму
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Можно отслеживать только ссылки: {FORUM_BASE}")

        # ---------------------------------------------------------
        #       ДЕТЕКТ КАТЕГОРИИ (forum vs thread)
        # ---------------------------------------------------------
        clean_url = url.split("&")[0]

        if "/index.php?forums/" in clean_url:
            typ = "forum"
        elif "/index.php?threads/" in clean_url:
            typ = "thread"
        else:
            return self.vk.send(peer_id, "❌ Эта ссылка не является ни разделом, ни темой.")

     
        latest = None
        try:
       
            if typ == "thread":
                if hasattr(self.tracker, "fetch_latest_post_id"):
                    latest = self.tracker.fetch_latest_post_id(clean_url)

        
            elif typ == "forum":
                html = self.tracker.fetch_html(clean_url)
                topics = parse_forum_topics(html, clean_url)
                if topics:
            
                    sortable = []
                    for t in topics:
                        dt = t.get("date") or ""
                        tid = int(t.get("tid", 0))
                        sortable.append((dt, tid, t))
                    
                    sortable.sort(key=lambda x: (x[0], x[1]))

                    last_topic = sortable[-1][2]
                    last_tid = sortable[-1][1]
                    last_date = sortable[-1][0]

                    latest = f"{last_tid};;{last_date}"

        except Exception:
            latest = None

        # ---------------------------------------------------------
        #        СОХРАНЯЕМ В БАЗУ
        # ---------------------------------------------------------
        add_track(peer_id, clean_url, typ)

        if latest:
            try:
                update_last(peer_id, clean_url, str(latest))
            except Exception:
                pass

 
        if typ == "forum":
            self.vk.send(peer_id, f"📁 Отслеживание раздела добавлено:\n{clean_url}")
        else:
            self.vk.send(peer_id, f"📄 Отслеживание темы добавлено:\n{clean_url}")

    def cmd_untrack(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /untrack <url>")
        url = normalize_url(parts[1])
        try:
            remove_track(peer_id, url)
            self.vk.send(peer_id, f"🗑 Отслеживание удалено: {url}")
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка remove track: {e}")

    def cmd_list(self, peer_id):
        try:
            rows = list_tracks(peer_id)
            if not rows:
                return self.vk.send(peer_id, "Нет отслеживаемых ссылок.")
            lines = [f"{u} ({t}) last: {l}" for u, t, l in rows]
            self.vk.send(peer_id, "📌 Отслеживаемые:\n" + "\n".join(lines))
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка list: {e}")

    def cmd_check(self, peer_id):
        try:
            self.vk.send(peer_id, "⏳ Запуск проверки…")
            ok = self.vk.trigger_check()
            self.vk.send(peer_id, "✅ Проверка запущена." if ok else "❌ Ошибка.")
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка trigger_check: {e}")


    def cmd_checkfa(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /checkfa <url>")
        url = normalize_url(parts[1])
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Только ссылки {FORUM_BASE}")
        try:
            posts = self.tracker.manual_fetch_posts(url)
        except Exception as e:
            return self.vk.send(peer_id, f"❌ Ошибка загрузки: {e}")
        if not posts:
            return self.vk.send(peer_id, "⚠️ Нет сообщений.")
        batch = []
        for p in posts:
            entry = (
                f"👤 {p['author']} • {p['date']}\n"
                f"{p['text'][:1200]}\n"
                f"🔗 {p['link']}"
            )
            batch.append(entry)
            if len(batch) >= 3:
                try:
                    self.vk.send_big(peer_id, "\n\n".join(batch))
                except Exception:
                    for b in batch:
                        self.vk.send(peer_id, b)
                batch = []
        if batch:
            try:
                self.vk.send_big(peer_id, "\n\n".join(batch))
            except Exception:
                for b in batch:
                    self.vk.send(peer_id, b)

  
    def cmd_ai(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /ai <текст>")
        try:
            ans = ask_ai(parts[1])
            self.vk.send(peer_id, ans)
        except Exception as e:
            self.vk.send(peer_id, f"AI Ошибка: {e}")


    def cmd_otvet(self, peer_id, parts):
        if len(parts) < 3:
            return self.vk.send(peer_id, "Использование: /otvet <url> <текст>")
        url = normalize_url(parts[1])
        text = parts[2]
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Только форум {FORUM_BASE}")
        try:
            res = self.tracker.post_message(url, text)
        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка: {e}")
        if res.get("ok"):
            try:
                if hasattr(self.tracker, 'fetch_latest_post_id'):
                    latest = self.tracker.fetch_latest_post_id(url)
                    if latest:
                        update_last(peer_id, url, str(latest))
            except Exception:
                pass
            return self.vk.send(peer_id, "✅ Сообщение отправлено.")
        else:
            return self.vk.send(peer_id, f"❌ Ошибка: {res.get('error')}")


    def cmd_tlist(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /tlist <url-раздела>")
        url = normalize_url(parts[1])
        if "forums" not in url.lower():
            return self.vk.send(peer_id, "❌ Это не ссылка на раздел.")
        try:
            html = self.tracker.fetch_html(url)
        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка fetch_html: {e}")
        if not html:
            return self.vk.send(peer_id, "❌ Не удалось загрузить HTML раздела.")
        topics = parse_forum_topics(html, url)
        if not topics:
            return self.vk.send(peer_id, "⚠️ Темы не найдены.")
        # берём первые 5 (в порядке parse)
        last5 = topics[:5]
        out = "📝 Последние темы раздела:\n\n"
        for t in last5:

            url_to_send = t['url']
            out += f"📄 {t['title']}\n🔗 {url_to_send}\n👤 {t['author']}\n\n"
        self.vk.send(peer_id, out)

    def cmd_tlistall(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /tlistall <url-раздела>")
        url = normalize_url(parts[1])
        if "forums" not in url.lower():
            return self.vk.send(peer_id, "❌ Это не ссылка на раздел.")
        try:
            html = self.tracker.fetch_html(url)
        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка fetch_html: {e}")
        if not html:
            return self.vk.send(peer_id, "❌ Не удалось загрузить раздел.")
        topics = parse_forum_topics(html, url)
        if not topics:
            return self.vk.send(peer_id, "⚠️ Темы не найдены.")
        # отправляем чанками
        max_len = 3500
        block = ""
        chunks = []
        for t in topics:
            line = f"📄 {t['title']}\n🔗 {t['url']}\n👤 {t['author']}\n\n"
            if len(block) + len(line) > max_len:
                chunks.append(block)
                block = ""
            block += line
        if block:
            chunks.append(block)
        for c in chunks:
            self.vk.send(peer_id, c)

  
    def cmd_addsh(self, peer_id, parts):
        """
        /addsh <name> <text>
        """
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /addsh <name> <text>")
      
        rest = parts[1] if len(parts) == 2 else parts[1] + (" " + (parts[2] if len(parts) > 2 else ""))

        m = re.match(r"(\S+)\s+(.+)", rest)
        if not m:
            return self.vk.send(peer_id, "Использование: /addsh <name> <text>")
        name = m.group(1).strip()
        text = m.group(2).strip()
        ok = add_template_for_peer(peer_id, name, text)
        if ok:
            self.vk.send(peer_id, f"✅ Шаблон '{name}' добавлен.")
        else:
            self.vk.send(peer_id, f"❌ Ошибка при сохранении шаблона '{name}'.")

    def cmd_removesh(self, peer_id, parts):
        """
        /removesh <name>
        """
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /removesh <name>")
        name = parts[1].strip()
        ok = remove_template_for_peer(peer_id, name)
        if ok:
            self.vk.send(peer_id, f"✅ Шаблон '{name}' удалён.")
        else:
            self.vk.send(peer_id, f"❌ Шаблон '{name}' не найден.")

    def cmd_shablon(self, peer_id, parts):
        """
        /shablon <name> <thread_url>
        Отправляет шаблон в тему форума
        """
        if len(parts) < 3:
            return self.vk.send(
                peer_id,
                "Использование:\n/shablon <имя_шаблона> <url_темы>"
            )

        name = parts[1].strip()
        url = normalize_url(parts[2].strip())

        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ URL должен быть на {FORUM_BASE}")

        txt = get_template(peer_id, name)
        if not txt:
            return self.vk.send(peer_id, f"❌ Шаблон '{name}' не найден.")

        try:
            res = self.tracker.post_message(url, txt)
        except Exception as e:
            return self.vk.send(peer_id, f"❌ Ошибка отправки: {e}")

        if not res:
            return self.vk.send(peer_id, "❌ Не удалось отправить сообщение")

        if res.get("ok") is True:
            return self.vk.send(
                peer_id,
                f"✅ Шаблон '{name}' успешно отправлен\n🔗 {url}"
            )

        return self.vk.send(
            peer_id,
            f"❌ Ошибка постинга: {res.get('error', 'неизвестная ошибка')}"
        )



    def cmd_profile(self, peer_id, parts):
        """
        /profile <url> - показать информацию о профиле (если доступно)
        """
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /profile <profile_url>")
        url = normalize_url(parts[1])
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ URL должен быть на {FORUM_BASE}")
        try:
            info = self._parse_profile(url)
            if not info:
                return self.vk.send(peer_id, "⚠️ Не удалось извлечь информацию о профиле.")
            lines = [
                f"👤 {info['username']}",
                f"🆔 ID: {info['user_id']}",
                f"📝 Сообщений: {info['message_count']}",
                f"⭐ Реакций: {info['reactions']}",
                f"🏆 Баллы: {info['points']}",
                f"📅 Регистрация: {info['registered']}",
                f"⏱ Активность: {info['last_activity']}",
            ]

            if info["about"]:
                lines.append(f"\n✉️ О себе:\n{info['about']}")

            self._send_long(peer_id, "\n".join(lines))
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка profile: {e}")

    def cmd_checkpr(self, peer_id, parts):
        """
        /checkpr <url> - посмотреть чужой профиль (как /profile, алиас)
        """
        return self.cmd_profile(peer_id, parts)

    def _parse_profile(self, url: str):
        from bs4 import BeautifulSoup
        import re

        html = self.tracker.fetch_html(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        data = {
            "username": "—",
            "user_id": "—",
            "registered": "—",
            "message_count": "—",
            "reactions": "—",
            "points": "—",
            "last_activity": "—",
            "about": ""
        }

    # 👤 Ник
        name = soup.select_one(".username, h1.p-title-value")
        if name:
            data["username"] = name.get_text(strip=True)

    # 🆔 ID
        m = re.search(r"\.(\d+)/?$", url)
        if m:
            data["user_id"] = m.group(1)

    # 📊 Статы (сообщения, реакции, баллы)
        for dl in soup.select(".memberHeader-stats dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if not dt or not dd:
                continue

            key = dt.get_text(strip=True).lower()
            val = dd.get_text(strip=True).replace(",", "")

            if "сообщ" in key:
                data["message_count"] = val
            elif "реакц" in key:
                data["reactions"] = val
            elif "балл" in key:
                data["points"] = val

    # 📅 Регистрация
        reg = soup.find("dt", string="Регистрация")
        if reg:
            time_el = reg.find_next("time")
            if time_el:
                data["registered"] = time_el.get_text(strip=True)

    # ⏱ Активность
        act = soup.find("dt", string="Активность")
        if act:
            time_el = act.find_next("time")
            if time_el:
                data["last_activity"] = time_el.get_text(strip=True)

    # ✉️ О себе
        about = soup.select_one(
            ".memberHeader-blurb, .p-profile-about, .userAbout"
        )
        if about:
            data["about"] = about.get_text(" ", strip=True)[:800]

        return data


  
    def cmd_kick(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /kick <id>")
        if peer_id <= 2000000000:
            return self.vk.send(peer_id, "Kick работает только в беседах.")
        uid = self._parse_user(parts[1])
        try:
            chat = peer_id - 2000000000
            self.vk.api.messages.removeChatUser(chat_id=chat, member_id=uid)
            self.vk.send(peer_id, f"👢 Кикнут: {uid}")
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка kick: {e}")

    def cmd_ban(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /ban <id>")
        uid = self._parse_user(parts[1])
        add_ban(peer_id, uid)
        if peer_id > 2000000000:
            try:
                chat = peer_id - 2000000000
                self.vk.api.messages.removeChatUser(chat_id=chat, member_id=uid)
            except Exception:
                pass
        self.vk.send(peer_id, f"🚫 Забанен: {uid}")

    def cmd_unban(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /unban <id>")
        uid = self._parse_user(parts[1])
        remove_ban(peer_id, uid)
        self.vk.send(peer_id, f"✅ Разбанен: {uid}")

    def cmd_mute(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /mute <id> <sec>")
        args = parts[1].split()
        uid = self._parse_user(args[0])
        sec = int(args[1]) if len(args) > 1 and args[1].isdigit() else 600
        self.vk.send(peer_id, f"🔇 {uid} замьючен на {sec} сек (симуляция).")

    def cmd_unmute(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /unmute <id>")
        uid = self._parse_user(parts[1])
        self.vk.send(peer_id, f"🔊 {uid} размьючен (симуляция).")

    def cmd_warn(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /warn <id>")
        uid = self._parse_user(parts[1])
        add_warn(peer_id, uid)
        self.vk.send(peer_id, f"⚠️ {uid} предупреждён. Всего: {get_warns(peer_id, uid)}")

    def cmd_warns(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /warns <id>")
        uid = self._parse_user(parts[1])
        self.vk.send(peer_id, f"Предупреждений у {uid}: {get_warns(peer_id, uid)}")

    def cmd_clearwarns(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /clearwarns <id>")
        uid = self._parse_user(parts[1])
        clear_warns(peer_id, uid)
        self.vk.send(peer_id, f"♻️ Предупреждения очищены: {uid}")

    def cmd_stats(self, peer_id):
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
            msg = (
                "📊 Статистика:\n"
                f"Отслеживаемых: {total_tracks}\n"
                f"Warn-строк: {total_warns}\n"
                f"Баны: {total_bans}"
            )
            self.vk.send(peer_id, msg)
        except Exception as e:
            self.vk.send(peer_id, f"Ошибка stats: {e}")

    def cmd_help(self, peer_id):
        self.vk.send(
            peer_id,
            "/track <url>\n/untrack <url>\n/list\n/check\n/checkfa <url>\n"
            "/tlist <url>\n/tlistall <url>\n"
            "/otvet <url> <text>\n/ai <text>\n"
            "/addsh <name> <text>\n/removesh <name>\n/shablon <name> <thread_url>\n"
            "/profile <url>\n/checkpr <url>\n"
            "/kick <id>\n/ban <id>\n/unban <id>\n"
            "/mute <id> <sec>\n/unmute <id>\n"
            "/warn <id>\n/warns <id>\n/clearwarns <id>\n/stats"
        )
        
    def cmd_debugtopics(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /debugtopics <url-раздела>")

        url = normalize_url(parts[1])
        if "forums" not in url.lower():
            return self.vk.send(peer_id, "❌ Это не ссылка на раздел.")

        try:
            html = self.tracker.fetch_html(url)
        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка fetch_html: {e}")

        if not html:
            return self.vk.send(peer_id, "❌ Не удалось загрузить страницу.")

        topics = parse_forum_topics(html, url)
        if not topics:
            return self.vk.send(peer_id, "⚠️ Темы не найдены.")

        out = "🔍 DEBUG TOPICS\n\n"

        for t in topics[:20]:
            out += (
                f"TID: {t.get('tid')}\n"
                f"TITLE: {t.get('title')}\n"
                f"AUTHOR: {t.get('author')}\n"
                f"PINNED: {t.get('pinned')}\n"
                f"CREATED: {t.get('created')}\n"
                f"URL: {t.get('url')}\n\n"
            )

    
        self._send_long(peer_id, out)

    def cmd_debugcheck(self, peer_id, parts):
        """
        /debugcheck <url> - показать что считает трекер новым (для этого чата).
        """
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование: /debugcheck <url>")
        url = normalize_url(parts[1])
        if not url.startswith(FORUM_BASE):
            return self.vk.send(peer_id, f"❌ Только {FORUM_BASE}")

        try:
            html = self.tracker.fetch_html(url)
            if not html:
                return self.vk.send(peer_id, "❌ Не удалось загрузить страницу (check cookies).")
            topics = parse_forum_topics(html, url)
            if not topics:
                return self.vk.send(peer_id, "⚠️ Темы не найдены.")
       
            lines = ["🔍 DEBUG TOPICS\n"]
            for t in topics[:30]:
                lines.append(
                    f"TID: {t.get('tid')} | TITLE: {t.get('title')}\n"
                    f"AUTHOR: {t.get('author')} | CREATED: {t.get('created')}\nURL: {t.get('url')}\n"
                )
            self._send_long(peer_id, "\n".join(lines))

 
            try:
                rows = list_tracks(peer_id)
                for u, typ, last in rows:
                    if normalize_url(u) == normalize_url(url):
                        self.vk.send(peer_id, f"Stored last for this peer: {last}")
                        break
            except Exception:
                pass

        except Exception as e:
            return self.vk.send(peer_id, f"Ошибка debugcheck: {e}")

    def cmd_reaction(self, peer_id, parts):
        if len(parts) < 2:
            return self.vk.send(peer_id, "Использование:\n/reaction <ссылка_на_пост>")

        post_url = parts[1]

        buttons = []
        row = []

        for i, (title, rid) in enumerate(REACTIONS.items(), 1):
            row.append({
                "action": {
                    "type": "callback",
                    "label": title,
                    "payload": {
                        "cmd": "reaction_btn",
                        "url": post_url,
                        "reaction_id": rid
                    }
                },
                "color": "secondary"
            })

            if i % 3 == 0:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        keyboard = {
            "inline": True,
            "buttons": buttons
        }

        self.vk.send(peer_id, "Выбери реакцию:", keyboard=keyboard)

    def handle_callback(self, event):
        payload = event["payload"]

        if payload.get("cmd") == "reaction_btn":
            url = payload["url"]
            reaction_id = payload["reaction_id"]

            ok, msg = self.tracker.react_to_post(url, reaction_id)

            if ok:
                self.vk.edit_message(
                    event["peer_id"],
                    event["conversation_message_id"],
                    "✅ Реакция поставлена"
                )
            else:
                self.vk.edit_message(
                    event["peer_id"],
                    event["conversation_message_id"],
                    f"❌ Ошибка: {msg}"
                )





    def _parse_user(self, s: str) -> int:
        if not s:
            return 0
        s = s.strip()
        m = re.search(r"id(\d+)", s)
        if m:
            return int(m.group(1))
        m2 = re.search(r"(\d+)", s)
        if m2:
            return int(m2.group(1))
        return 0

    def _send_long(self, peer_id: int, text: str):
        """Разбивает длинный текст на чанки и отправляет в VK."""
        if not text:
            return
        try:
            if hasattr(self.vk, 'send_big'):
                self.vk.send_big(peer_id, text)
                return
        except Exception:
            pass
        max_chunk = 3800
        chunks = [text[i:i + max_chunk] for i in range(0, len(text), max_chunk)]
        for ch in chunks:
            try:
                self.vk.send(peer_id, ch)
            except Exception:
                print(f"[CMD] Failed to send chunk to {peer_id}")


