# bot/permissions.py
import os

def is_admin(vk_api, peer_id: int, user_id: int) -> bool:
    """
    Simple admin check:
    - ADMINS env var can list admin ids separated by comma
    - otherwise, tries to check conversation members for chat admin/owner flags
    """
    admin_env = os.getenv("ADMINS", "")
    try:
        if admin_env:
            admins = [int(x.strip()) for x in admin_env.split(",") if x.strip()]
            if int(user_id) in admins:
                return True
    except Exception:
        pass

    try:
        # For group chats, get conversation members and check flags
        conv = vk_api.messages.getConversationMembers(peer_id=peer_id)
        for it in conv.get("items", []):
            mid = it.get("member_id")
            if mid == user_id and (it.get("is_admin") or it.get("is_owner")):
                return True
    except Exception:
        pass

    return False
