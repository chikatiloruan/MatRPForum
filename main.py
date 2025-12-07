# =====================================================
# MATRP FORUM TRACKER — MAIN
# Автор: 4ikatilo
# =====================================================

import sys
import time
import threading
import os
import importlib.util
import itertools

from colorama import Fore, Style, init
init(autoreset=True)

# =====================================================
# GLOBAL MODES
# =====================================================

RUN_MODE = "RELEASE"   # DEBUG | RELEASE
STARTUP_STYLE = "ROCKET"  # ROCKET | CLASSIC

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

        print(Fore.GREEN + "\n✅ Конфигурация сохранена. Перезапуск НЕ требуется.\n")

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
    XF_CSRF
)

from bot.vk_bot import VKBot
from bot.forum_tracker import ForumTracker, stay_online_loop

# =====================================================
# INFO
# =====================================================

BOT_VERSION = "2.3.1"

# =====================================================
# UI — BANNER
# =====================================================

LOGO = r"""
 ███╗   ███╗ █████╗ ████████╗██████╗ ██████╗ 
 ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗
 ██╔████╔██║███████║   ██║   ██████╔╝██████╔╝
 ██║╚██╔╝██║██╔══██║   ██║   ██╔═══╝ ██╔══██╗
 ██║ ╚═╝ ██║██║  ██║   ██║   ██║     ██║  ██║
 ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝
"""

def smooth_logo():
    os.system("cls" if os.name == "nt" else "clear")
    for line in LOGO.splitlines():
        print(Fore.CYAN + line)
        time.sleep(0.06)
    print(Fore.MAGENTA + "\n      MATRP FORUM TRACKER — VK EDITION")
    print(Fore.GREEN + f"      VERSION {BOT_VERSION} | MODE {RUN_MODE}\n")


# =====================================================
# ROCKET STARTUP
# =====================================================

def rocket_startup():
    os.system("cls" if os.name == "nt" else "clear")

    for i in range(5, 0, -1):
        print(Fore.YELLOW + f"T-{i}")
        time.sleep(0.5)

    sequence = [
        "Fuel system",
        "Navigation core",
        "Forum session",
        "VK uplink",
        "Tracker threads"
    ]

    for s in sequence:
        print(Fore.CYAN + f"{s:<20}", end="")
        time.sleep(0.5)
        print(Fore.GREEN + " OK")

    for h in range(6):
        print("\n" * 1 + " " * (10 - h) + Fore.RED + "🚀")
        time.sleep(0.15)
        os.system("cls" if os.name == "nt" else "clear")

    smooth_logo()


# =====================================================
# REAL-TIME STATUS
# =====================================================

def status_loop(vk, tracker):
    spinner = itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"])
    while True:
        icon = next(spinner)
        vk_s = "ONLINE" if vk.is_alive else "OFFLINE"
        forum_s = "ONLINE" if tracker._running else "OFFLINE"

        line = (
            Fore.CYAN + f"[ {icon} STATUS ] "
            + Fore.GREEN + f"VK: {vk_s} "
            + Fore.YELLOW + f"| FORUM: {forum_s} "
            + Fore.MAGENTA + f"| MODE: {RUN_MODE}"
        )

        print("\r" + line + " " * 10, end="", flush=True)
        time.sleep(1)


# =====================================================
# RUN
# =====================================================

def run():
    if STARTUP_STYLE == "ROCKET":
        rocket_startup()
    else:
        smooth_logo()

    if RUN_MODE == "DEBUG":
        print(Fore.YELLOW + "[DEBUG MODE ENABLED]\n")

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
    threading.Thread(target=status_loop, args=(vk, tracker), daemon=True).start()

    while True:
        time.sleep(5)


if __name__ == "__main__":
    run()
