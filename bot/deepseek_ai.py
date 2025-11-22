import os
import requests

API_KEY = os.getenv("DEEPSEEK_API_KEY")
API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat")  # пример; заменяй, если у тебя другой URL

def ask_ai(prompt: str) -> str:
    if not API_KEY:
        return "AI not configured."
    try:
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role":"user", "content": prompt}],
            "max_tokens": 512
        }
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        # формат ответа может отличаться, попробуем извлечь безопасно
        if isinstance(data, dict):
            if data.get("choices"):
                return data["choices"][0].get("message", {}).get("content", "") or str(data)
            if data.get("result"):
                return data.get("result", "")
        return str(data)
    except Exception as e:
        return f"AI error: {e}"

