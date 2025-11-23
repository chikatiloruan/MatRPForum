# bot/vk_bot.py
import os
import threading
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from .command_handler import CommandHandler
from .storage import init_db

from config import VK_TOKEN

class VKBot:
    def __init__(self):
        init_db()
        token = VK_TOKEN
        if not token:
            raise RuntimeError("VK_TOKEN not set in config.py")
        self.vk_session = vk_api.VkApi(token=token)
        self.api = self.vk_session.get_api()
        gid = self.api.groups.getById()[0]['id']
        self.group_id = gid
        self.longpoll = VkBotLongPoll(self.vk_session, gid)
        self.handler = CommandHandler(self)
        self._trigger_check = None

    def start(self):
        t = threading.Thread(target=self._longpoll_loop, daemon=True)
        t.start()

    def _longpoll_loop(self):
        print("VK longpoll started")
        for event in self.longpoll.listen():
            try:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    msg = event.object.message
                    text = msg.get("text", "") or ""
                    peer = msg["peer_id"]
                    from_id = msg.get("from_id", 0)
                    if text.startswith("/"):
                        try:
                            self.handler.handle(text, peer, from_id)
                        except Exception as e:
                            print("Command handler error:", e)
            except Exception as e:
                print("Longpoll error:", e)

    def send(self, peer_id: int, text: str):
        try:
            self.api.messages.send(peer_id=peer_id, message=text, random_id=0)
        except Exception as e:
            print("VK send error:", e)

    def set_trigger(self, fn):
        self._trigger_check = fn

    def trigger_check(self):
        if self._trigger_check:
            try:
                self._trigger_check()
                return True
            except Exception:
                return False
        return False
