import sys
import time
import threading
import os
import importlib.util
import getpass
import requests
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


def create_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("# ================================\n")
        f.write("#  MATRP FORUM TRACKER CONFIG\n")
        f.write("#  Created automatically\n")
        f.write("# ================================\n\n")

        for k, v in FIXED_VALUES.items():
            f.write(f'{k} = "{v}"\n')

        f.write("\n")

        for k in REQUIRED_FIELDS:
            if k == "POLL_INTERVAL_SEC":
                f.write(f"{k} = 60\n")
            else:
                f.write(f'{k} = ""\n')

    print(Fore.GREEN + "✅ Создан config.py")
    print(Fore.YELLOW + "👉 Заполни данные и запусти бота снова\n")
    sys.exit(0)


def update_config(values: dict):
    with open(CONFIG_FILE, "a", encoding="utf-8") as f:
        f.write("\n# ===== Auto-added fields =====\n")
        for k, v in values.items():
            if isinstance(v, int):
                f.write(f"{k} = {v}\n")
            else:
                f.write(f'{k} = "{v}"\n')


def ensure_config():
    if not os.path.exists(CONFIG_FILE):
        create_config()

    config = load_config()
    to_add = {}

    print(Fore.CYAN + "🔧 Проверка конфигурации...\n")

    for key, desc in REQUIRED_FIELDS.items():
        if not hasattr(config, key) or not getattr(config, key):
            if key in ("XF_PASS", "ADMIN_PASS", "DEBUG_PASS"):
                value = getpass.getpass(f"Введите {desc}: ")
            elif key == "POLL_INTERVAL_SEC":
                value = int(input(f"Введите {desc}: "))
            else:
                value = input(f"Введите {desc}: ")

            to_add[key] = value

    if to_add:
        update_config(to_add)
        print(Fore.GREEN + "\n✅ config.py обновлён")
        print(Fore.YELLOW + "👉 Перезапусти бота\n")
        sys.exit(0)

    return config


# =====================================================
# LOAD CONFIG
# =====================================================

config = ensure_config()

from config import (
    VK_TOKEN,
    XF_USER,
    XF_TFA_TRUST,
    XF_SESSION,
    XF_CSRF,
    FORUM_BASE,
    POLL_INTERVAL_SEC
)

from bot.vk_bot import VKBot
from bot.forum_tracker import ForumTracker, stay_online_loop

# =====================================================
# INFO
# =====================================================

BOT_VERSION = "2.3.1"
AUTHOR = "Создатель: 4ikatilo"
AUTHOR_TG = "Telegram: @c4ikatillo"
AUTHOR_VK = "VK: https://vk.com/ashot.nageroine"

# =====================================================
# UI / VISUALS
# =====================================================

def clear_console():
    os.system("cls" if os.name == "nt" else "clear")


def loader():
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    for i in range(20):
        print(Fore.MAGENTA + f"\r💀 Загрузка системы {frames[i % len(frames)]}", end="")
        time.sleep(0.1)
    print()


def banner():
    print(Fore.RED + r"""
 ███╗   ███╗ █████╗ ████████╗██████╗ ██████╗ 
 ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗
 ██╔████╔██║███████║   ██║   ██████╔╝██████╔╝
 ██║╚██╔╝██║██╔══██║   ██║   ██╔═══╝ ██╔══██╗
 ██║ ╚═╝ ██║██║  ██║   ██║   ██║     ██║  ██║
 ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝
""" + Style.RESET_ALL)

    print(Fore.MAGENTA + "──────────────────────────────────────────────────────────")
    print(Fore.GREEN   + f" 🔥 Версия: {BOT_VERSION}")
    print(Fore.CYAN    + f" 👤 {AUTHOR}")
    print(Fore.YELLOW  + f" 💬 {AUTHOR_TG}")
    print(Fore.BLUE    + f" 🌐 {AUTHOR_VK}")
    print(Fore.MAGENTA + "──────────────────────────────────────────────────────────")
    print(Fore.GREEN   + " 🌐 VK STATUS: ONLINE")
    print(Fore.GREEN   + " 🌐 FORUM STATUS: ONLINE")
    print(Fore.CYAN    + "\n✅ Бот запущен. Ожидание событий...\n")


# =====================================================
# RUN
# =====================================================

def run():
    clear_console()
    loader()
    clear_console()
    banner()

    vk = VKBot()
    tracker = ForumTracker(
        XF_USER,
        XF_TFA_TRUST,
        XF_SESSION,
        vk
    )

    vk.start()
    tracker.start()

    threading.Thread(target=stay_online_loop, daemon=True).start()

    while True:
        time.sleep(5)


if __name__ == "__main__":
    run()
