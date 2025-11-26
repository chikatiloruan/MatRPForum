# main.py
import sys
import time
import threading
from colorama import Fore, Style, init

from config import VK_TOKEN, XF_USER, XF_TFA_TRUST, XF_SESSION
from bot.vk_bot import VKBot
from bot.forum_tracker import ForumTracker

init(autoreset=True)

# ============================================================
# БАННЕР (стиль НОВЫЙ)
# ============================================================
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

    print(Fore.MAGENTA + "──────────────────────────────────────────────────" + Style.RESET_ALL)
    print(Fore.GREEN   + " 🔗 VK Longpoll Bot подключается..." + Style.RESET_ALL)
    print(Fore.YELLOW  + " 🛰 Отслеживание форума MatRP активно" + Style.RESET_ALL)
    print(Fore.CYAN    + " ✉ Ответы с VK прямо в темы форума" + Style.RESET_ALL)
    print(Fore.MAGENTA + "──────────────────────────────────────────────────\n" + Style.RESET_ALL)


# ============================================================
# ПРОВЕРКА КОНФИГА (как в СТАРОЙ версии)
# ============================================================
def check_config():
    missing = []

    if not VK_TOKEN:       missing.append("VK_TOKEN")
    if not XF_USER:        missing.append("XF_USER")
    if not XF_TFA_TRUST:   missing.append("XF_TFA_TRUST")
    if not XF_SESSION:     missing.append("XF_SESSION")

    if missing:
        print(Fore.RED + "❌ В config.py отсутствуют параметры:" + Style.RESET_ALL)
        for m in missing:
            print(Fore.YELLOW + f" → {m}" + Style.RESET_ALL)

        print(Fore.CYAN + "\nЗаполни config.py и перезапусти бота.\n" + Style.RESET_ALL)
        sys.exit(1)


# ============================================================
# ОСНОВНОЙ ЗАПУСК (логика старая)
# ============================================================
def run():
    banner()
    check_config()

    print(Fore.CYAN + "[INIT] Инициализация VK бота..." + Style.RESET_ALL)
    vk = VKBot()  # ← СТАРАЯ ЛОГИКА: без аргументов

    print(Fore.CYAN + "[INIT] Инициализация форум-трекера..." + Style.RESET_ALL)
    tracker = ForumTracker(XF_USER, XF_TFA_TRUST, XF_SESSION, vk)  # ← СТАРАЯ ЛОГИКА

    print(Fore.GREEN + "\n✔ Всё готово! Бот работает.\n" + Style.RESET_ALL)

    # --- Запуск потоков как раньше ---
    threading.Thread(target=vk.longpoll_loop, daemon=True).start()
    threading.Thread(target=tracker.loop, daemon=True).start()

    # --- Держим процесс ---
    while True:
        time.sleep(3)


if __name__ == "__main__":
    run()
