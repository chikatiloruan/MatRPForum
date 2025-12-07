
import os
import threading
import time
import sys
import traceback
from typing import Callable

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType

from .command_handler import CommandHandler
from .storage import init_db
from config import VK_TOKEN


VK_MSG_LIMIT = 5500

class VKBot:
    def __init__(self):
        init_db()
        token = VK_TOKEN
        if not token:
            raise RuntimeError("VK_TOKEN not set in config.py")
        self.vk_session = vk_api.VkApi(token=token)
        self.api = self.vk_session.get_api()
        gid = self.api.groups.getById()[0]["id"]
        self.group_id = gid
        self.longpoll = VkBotLongPoll(self.vk_session, gid)
        self.handler = CommandHandler(self)
        self._trigger_check_callback = None
        self._running = False
        self._lp_thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._lp_thread = threading.Thread(target=self._longpoll_loop, daemon=True)
        self._lp_thread.start()
        print("VK longpoll loop started")

    def stop(self):
        self._running = False
       
        print("VKBot stopped")

    def _longpoll_loop(self):
        print("VKBot longpoll listening...")
        for event in self.longpoll.listen():
            if not self._running:
                break
            try:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.object.message
                    text = msg.get("text", "") or ""
                    peer = msg["peer_id"]
                    from_id = msg.get("from_id") or 0
                   
                    if text and text.startswith("/"):
                        try:
                            self.handler.handle(text, peer, from_id)
                        except Exception as e:
                            print("Command handler exception:", e)
                            traceback.print_exc()
            except Exception as e:
                print("Longpoll error:", e)
                traceback.print_exc()
           
                time.sleep(1)

    def send(self, peer_id: int, text: str):
        try:
            self.api.messages.send(peer_id=peer_id, message=text, random_id=0)
        except Exception as e:
            print("VK send error:", e)

    def send_big(self, peer_id: int, text: str):
        if not text:
            return

        parts = []
        cur = ""
        for paragraph in text.split("\n\n"):
            if len(cur) + len(paragraph) + 2 <= VK_MSG_LIMIT:
                cur += (paragraph + "\n\n")
            else:
                if cur:
                    parts.append(cur.strip())
                if len(paragraph) > VK_MSG_LIMIT:
                
                    for i in range(0, len(paragraph), VK_MSG_LIMIT):
                        parts.append(paragraph[i:i+VK_MSG_LIMIT])
                    cur = ""
                else:
                    cur = paragraph + "\n\n"
        if cur:
            parts.append(cur.strip())
        for p in parts:
            self.send(peer_id, p)

    def set_trigger(self, fn: Callable):
        self._trigger_check_callback = fn

    def trigger_check(self) -> bool:
        if self._trigger_check_callback:
            try:
                self._trigger_check_callback()
                return True
            except Exception as e:
                print("trigger_check error:", e)
                return False
        return False
    def longpoll_loop(self):
        """Публичный метод для main.py"""
        return self._longpoll_loop()
