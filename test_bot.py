"""Мини-тест Telegram бота."""
import os
import sys
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    sys.exit("Укажите TELEGRAM_BOT_TOKEN в переменной окружения перед запуском")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

try:
    r = requests.get(API_URL + "getMe", timeout=5)
    data = r.json()
    if data.get("ok"):
        print("✅ Токен работает")
        print(f"Имя бота: {data['result']['first_name']}")
        print(f"Username: @{data['result']['username']}")
    else:
        print("❌ Ошибка getMe:", data)
except Exception as e:
    print(f"❌ Ошибка getMe: {e}")

try:
    r = requests.get(API_URL + "getUpdates?offset=-1", timeout=5)
    data = r.json()
    if data.get("ok") and data.get("result"):
        print("\n📨 Есть непрочитанные обновления")
    else:
        print("\nℹ️ Обновлений нет или ответ не ok")
except Exception as e:
    print(f"\n❌ Ошибка getUpdates: {e}")
