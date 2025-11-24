# bot/permissions.py
import os

def is_admin(vk_api, peer_id: int, user_id: int) -> bool:
    """
    1) If ADMINS env var contains user ids -> they are admins
    2) For chat: query messages.getConversationMembers and check is_admin/is_owner
    """
    try:
        env = os.getenv("ADMINS", "")
        if env:
            admins = [int(x.strip()) for x in env.split(",") if x.strip()]
            if int(user_id) in admins:
                return True
    except Exception:
        pass

    try:
        if vk_api and peer_id:
            conv = vk_api.messages.getConversationMembers(peer_id=peer_id)
            items = conv.get("items", [])
            for it in items:
                mid = it.get("member_id")
                if mid == user_id and (it.get("is_admin") or it.get("is_owner")):
                    return True
    except Exception:
        pass

    return False
