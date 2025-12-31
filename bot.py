import os
import json
import time
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

# ========= НАСТРОЙКИ =========
TELEGRAM_BOT_TOKEN = "8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0"
ADMIN_CHAT_ID = 979000473  # Твой ID

# Ссылка на твой сайт (WebApp)
WEBAPP_URL = "https://market-equinox.vercel.app/"

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

# ========= ЛОГИРОВАНИЕ =========
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= ПУТИ =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Если products.json лежит рядом с bot.py или в папке webapp - проверь путь!
PRODUCTS_JSON_PATH = os.path.join(BASE_DIR, "products.json") 
DB_PATH = os.path.join(BASE_DIR, "shop.db")

# ========= РАБОТА С БД (SQLite) =========
def init_db():
    """Создает таблицу заказов, если её нет"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            items_json TEXT,
            total_price REAL,
            contact_json TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_order_to_db(user_id, user_name, items, total_price, contact):
    """Сохраняет заказ в БД"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO orders (user_id, user_name, items_json, total_price, contact_json)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        user_id,
        user_name,
        json.dumps(items, ensure_ascii=False),
        total_price,
        json.dumps(contact, ensure_ascii=False)
    ))
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id

# ========= ЗАГРУЗКА ТОВАРОВ =========
PRODUCTS: List[Dict[str, Any]] = []
PRODUCTS_BY_ID: Dict[int, Dict[str, Any]] = {}

def load_products() -> None:
    global PRODUCTS, PRODUCTS_BY_ID
    try:
        if not os.path.exists(PRODUCTS_JSON_PATH):
            # Попробуем поискать в текущей директории, если путь сложный
            logger.warning(f"File not found at {PRODUCTS_JSON_PATH}, checking current dir")
            local_path = "products.json"
            if os.path.exists(local_path):
                 with open(local_path, "r", encoding="utf-8") as f:
                    PRODUCTS = json.load(f)
            else:
                logger.error("products.json not found anywhere!")
                return
        else:
            with open(PRODUCTS_JSON_PATH, "r", encoding="utf-8") as f:
                PRODUCTS = json.load(f)
                
        PRODUCTS_BY_ID = {int(p["id"]): p for p in PRODUCTS}
        logger.info(f"Products loaded: {len(PRODUCTS)} items")
    except Exception as e:
        logger.exception(f"Failed to load products: {e}")

def get_product(pid: int):
    return PRODUCTS_BY_ID.get(pid)

def find_option(product, opt_id):
    if not product or not opt_id: return None
    if "options" in product:
        for o in product["options"]:
            if str(o["id"]) == str(opt_id):
                return o
    return None

# ========= TELEGRAM API HELPERS =========
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if parse_mode: data["parse_mode"] = parse_mode
    if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
    
    try:
        requests.post(API_URL + "sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Send Error: {e}")

def format_contact(c):
    if not c: return "Нет данных"
    return (
        f"👤 {c.get('name')}\n"
        f"📞 {c.get('phone')}\n"
        f"🏠 {c.get('address')}\n"
        f"💬 {c.get('comment')}"
    )

# ========= ОБРАБОТКА ЗАКАЗОВ =========

def process_webapp_data(message):
    chat_id = message["chat"]["id"]
    try:
        data_str = message["web_app_data"]["data"]
        payload = json.loads(data_str)
    except:
        return send_message(chat_id, "Ошибка данных WebApp")

    action = payload.get("action")
    contact = payload.get("contact", {})
    user = message.get("from", {})
    user_name = f"{user.get('first_name','')} {user.get('last_name','')}".strip()
    
    order_items = []
    total_price = 0

    # ЛОГИКА СБОРА ТОВАРОВ
    if action == "buy":
        # Одиночная покупка
        pid = int(payload.get("productId"))
        oid = payload.get("optionId")
        p = get_product(pid)
        if p:
            price = p["price"]
            opt = find_option(p, oid)
            name = p["name"] + (f" ({opt['name']})" if opt else "")
            
            order_items.append({"name": name, "price": price, "qty": 1})
            total_price += price

    elif action == "cart_checkout":
        # Корзина
        raw_items = payload.get("items", [])
        for item in raw_items:
            pid = int(item["productId"])
            oid = item.get("optionId")
            qty = item.get("qty", 1)
            
            p = get_product(pid)
            if p:
                price = p["price"]
                opt = find_option(p, oid)
                name = p["name"] + (f" ({opt['name']})" if opt else "")
                
                order_items.append({"name": name, "price": price, "qty": qty})
                total_price += (price * qty)

    if not order_items:
        return send_message(chat_id, "Ошибка: товары не найдены или корзина пуста.")

    # СОХРАНЯЕМ В БД
    order_id = save_order_to_db(chat_id, user_name, order_items, total_price, contact)

    # ФОРМИРУЕМ ЧЕК ДЛЯ АДМИНА
    items_str = "\n".join([f"- {i['name']} x{i['qty']} = {i['price']*i['qty']} грн" for i in order_items])
    
    admin_msg = (
        f"🔥 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\n\n"
        f"{items_str}\n"
        f"➖➖➖➖➖➖\n"
        f"💰 <b>Итого: {total_price} грн</b>\n\n"
        f"📂 <b>Клиент:</b>\n"
        f"{format_contact(contact)}\n"
        f"Telegram: @{user.get('username', 'net_nika')}"
    )

    send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML")
    
    # ОТВЕТ КЛИЕНТУ
    send_message(chat_id, f"✅ Спасибо! Заказ #{order_id} принят.\nМенеджер скоро свяжется с тобой.")

# ========= MAIN LOOP =========

def main():
    init_db()
    load_products()
    logger.info("Bot started...")
    
    offset = None
    while True:
        try:
            params = {"timeout": 50, "offset": offset}
            r = requests.get(API_URL + "getUpdates", params=params, timeout=60)
            data = r.json()
            
            if not data.get("ok"): continue
            
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                
                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    
                    if "web_app_data" in msg:
                        process_webapp_data(msg)
                    
                    elif "text" in msg:
                        txt = msg["text"]
                        if txt == "/start":
                            kb = {
                                "keyboard": [[{"text": "🛒 Открыть Shop", "web_app": {"url": WEBAPP_URL}}]],
                                "resize_keyboard": True
                            }
                            send_message(chat_id, "Привет! Жми кнопку ниже 👇", reply_markup=kb)

        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
