# =====================================================
# MATRP FORUM TRACKER — MAIN
# Автор: 4ikatilo
# =====================================================

import sys
import time
import threading
import os
import importlib.util

from colorama import Fore, Style, init

init(autoreset=True)

# =====================================================
# CONFIG MANAGER
# =====================================================

CONFIG_FILE = "config.py"

FIXED_VALUES = {
    "FORUM_BASE": "https://forum.matrp.ru"
}

REQUIRED_FIELDS = {
    "VK_TOKEN": "VK Token бота",

    "XF_USER": "Cookie XF_USER",
    "XF_TFA_TRUST": "Cookie XF_TFA_TRUST",
    "XF_SESSION": "Cookie XF_SESSION",
    "XF_CSRF": "Cookie XF_CSRF",

    "XF_LOGIN": "Логин форума",
    "XF_PASS": "Пароль форума",

    "ADMIN_USER": "Админ логин",
    "ADMIN_PASS": "Админ пароль",

    "DEBUG_PASS": "DEBUG пароль",

    "POLL_INTERVAL_SEC": "Интервал проверки (сек.)",
}


def load_config():
    spec = importlib.util.spec_from_file_location("config", CONFIG_FILE)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def ensure_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("# Автоматически созданный config.py\n\n")
            f.write('FORUM_BASE = "https://forum.matrp.ru"\n\n')
            for k in REQUIRED_FIELDS:
                if k == "POLL_INTERVAL_SEC":
                    f.write("POLL_INTERVAL_SEC = 60\n")
                else:
                    f.write(f'{k} = ""\n')

    config = load_config()
    updated = False

    print(Fore.CYAN + "\n🔧 Первичная настройка:\n")

    for key, desc in REQUIRED_FIELDS.items():
        val = getattr(config, key, "")

        if not val:
            value = input(Fore.YELLOW + f"{desc}: ")
            setattr(config, key, int(value) if key == "POLL_INTERVAL_SEC" else value)
            updated = True

    if updated:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("# Автоматически созданный config.py\n\n")
            f.write('FORUM_BASE = "https://forum.matrp.ru"\n\n')
            for key in REQUIRED_FIELDS:
                val = getattr(config, key)
                if isinstance(val, int):
                    f.write(f"{key} = {val}\n")
                else:
                    f.write(f'{key} = "{val}"\n')

        print(Fore.GREEN + "\n✅ Конфигурация сохранена!\n")

    return config


config = ensure_config()

# =====================================================
# IMPORTS FROM CONFIG
# =====================================================

from config import (
    VK_TOKEN,
    XF_USER,
    XF_TFA_TRUST,
    XF_SESSION,
    XF_CSRF,
    POLL_INTERVAL_SEC
)

from bot.vk_bot import VKBot
from bot.forum_tracker import ForumTracker, stay_online_loop

# =====================================================
# INFO
# =====================================================

BOT_VERSION = "2.3.1"

# =====================================================
# UI
# =====================================================

def banner():
    print(Fore.CYAN + r"""
 ███╗   ███╗ █████╗ ████████╗██████╗ ██████╗ 
 ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗
 ██╔████╔██║███████║   ██║   ██████╔╝██████╔╝
 ██║╚██╔╝██║██╔══██║   ██║   ██╔═══╝ ██╔══██╗
 ██║ ╚═╝ ██║██║  ██║   ██║   ██║     ██║  ██║
 ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝

      MATRP FORUM TRACKER — VK EDITION
""" + Style.RESET_ALL)

    print(Fore.MAGENTA + "──────────────────────────────────────────────────────────")
    print(Fore.GREEN   + f" 🔥 Версия: {BOT_VERSION}")
    print(Fore.CYAN    + " 👤 Создатель: 4ikatilo")
    print(Fore.YELLOW  + " 💬 Telegram: @c4ikatillo")
    print(Fore.BLUE    + " 🌐 VK: vk.com/ashot.nageroine")
    print(Fore.MAGENTA + "──────────────────────────────────────────────────────────\n")


def startup_animation():
    steps = [
        "🔐 Авторизация VK",
        "🍪 Проверка cookies форума",
        "📡 Подключение к MatRP",
        "🧠 Инициализация трекеров",
        "🚀 Запуск сервисов"
    ]

    for s in steps:
        print(Fore.CYAN + s + " ...", end="")
        time.sleep(0.7)
        print(Fore.GREEN + " OK")

    print(Fore.RED + r"""
      ☠ VK / Forum Status ☠
      ████████████████████
          ONLINE
    """)


# =====================================================
# RUN
# =====================================================

def run():
    banner()
    startup_animation()

    print(Fore.CYAN + "\n[INIT] VK Bot...")
    vk = VKBot()

    print(Fore.CYAN + "[INIT] Forum Tracker...")
    tracker = ForumTracker(
        XF_USER,
        XF_TFA_TRUST,
        XF_SESSION,
        vk
    )

    print(Fore.GREEN + "\n✅ Бот успешно запущен и работает!\n")

    vk.start()
    tracker.start()

    threading.Thread(target=stay_online_loop, daemon=True).start()

    while True:
        time.sleep(3)


if __name__ == "__main__":
    run()
