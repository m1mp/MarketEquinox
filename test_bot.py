"""Быстрый тест бота"""
import requests

TELEGRAM_BOT_TOKEN = "8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0"
API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

# Проверяем, что бот работает
try:
    r = requests.get(API_URL + "getMe", timeout=5)
    data = r.json()
    if data.get("ok"):
        print("✅ Бот работает!")
        print(f"Имя бота: {data['result']['first_name']}")
        print(f"Username: @{data['result']['username']}")
    else:
        print("❌ Ошибка:", data)
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")

# Проверяем последние обновления
try:
    r = requests.get(API_URL + "getUpdates?offset=-1", timeout=5)
    data = r.json()
    if data.get("ok") and data.get("result"):
        print("\n📨 Последние обновления получены")
    else:
        print("\n⚠️ Нет обновлений или ошибка")
except Exception as e:
    print(f"\n❌ Ошибка получения обновлений: {e}")

