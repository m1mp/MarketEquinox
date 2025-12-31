import os
import json
import time
import logging
import sqlite3
import hashlib
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

# ========= НАСТРОЙКИ =========
TELEGRAM_BOT_TOKEN = "8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0"
ADMIN_CHAT_ID = 979000473  # Твой ID

# Ссылка на твой сайт (WebApp)
WEBAPP_URL = "https://market-equinox.vercel.app/"

# LiqPay настройки (получи на https://www.liqpay.ua/)
LIQPAY_PUBLIC_KEY = "your_public_key"  # Замени на свой
LIQPAY_PRIVATE_KEY = "your_private_key"  # Замени на свой
LIQPAY_SANDBOX = True  # True для тестирования, False для продакшена

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
            payment_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Добавляем колонку payment_status если её нет
    try:
        c.execute('ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT "pending"')
    except:
        pass  # Колонка уже существует
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

def get_orders(status=None, limit=50):
    """Получает заказы из БД"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if status:
        c.execute('SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?', (status, limit))
    else:
        c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    
    # Преобразуем в словари
    columns = ['id', 'user_id', 'user_name', 'items_json', 'total_price', 'contact_json', 'status', 'created_at']
    orders = []
    for row in rows:
        order = dict(zip(columns, row))
        order['items'] = json.loads(order['items_json'])
        order['contact'] = json.loads(order['contact_json'])
        orders.append(order)
    return orders

def update_order_status(order_id, new_status):
    """Обновляет статус заказа"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def get_order(order_id):
    """Получает один заказ по ID"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    columns = ['id', 'user_id', 'user_name', 'items_json', 'total_price', 'contact_json', 'status', 'created_at']
    order = dict(zip(columns, row))
    order['items'] = json.loads(order['items_json'])
    order['contact'] = json.loads(order['contact_json'])
    return order

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

# ========= ПЛАТЕЖНАЯ СИСТЕМА (LiqPay) =========

def generate_liqpay_link(order_id, amount, description, result_url=None):
    """Генерирует ссылку на оплату через LiqPay"""
    if LIQPAY_PUBLIC_KEY == "your_public_key":
        return None  # Платежи не настроены
    
    data = {
        "public_key": LIQPAY_PUBLIC_KEY,
        "version": "3",
        "action": "pay",
        "amount": str(amount),
        "currency": "UAH",
        "description": description,
        "order_id": str(order_id),
        "sandbox": "1" if LIQPAY_SANDBOX else "0",
        "result_url": result_url or WEBAPP_URL,
        "server_url": WEBAPP_URL + "payment_callback"  # Для обработки callback
    }
    
    # Кодируем данные
    data_str = json.dumps(data, separators=(',', ':'))
    data_encoded = base64.b64encode(data_str.encode('utf-8')).decode('utf-8')
    
    # Создаем подпись
    signature_string = LIQPAY_PRIVATE_KEY + data_encoded + LIQPAY_PRIVATE_KEY
    signature = base64.b64encode(hashlib.sha1(signature_string.encode('utf-8')).digest()).decode('utf-8')
    
    # Формируем ссылку
    payment_url = f"https://www.liqpay.ua/api/3/checkout?data={data_encoded}&signature={signature}"
    return payment_url

def verify_liqpay_signature(data, signature):
    """Проверяет подпись от LiqPay"""
    expected_signature = base64.b64encode(
        hashlib.sha1((LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode('utf-8')).digest()
    ).decode('utf-8')
    return expected_signature == signature

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
            pid = int(item.get("productId") or item.get("id", 0))  # Поддержка обоих форматов
            oid = item.get("optionId")
            qty = item.get("qty", 1)
            
            p = get_product(pid)
            if p:
                price = p["price"]
                opt = find_option(p, oid)
                name = p["name"] + (f" ({opt['name']})" if opt else "")
                
                order_items.append({"name": name, "price": price, "qty": qty})
                total_price += (price * qty)
        
        # Учитываем промокод, если есть финальная цена из WebApp
        promo_code = payload.get("promo")
        final_price = payload.get("totalPrice")
        if final_price is not None:
            total_price = float(final_price)  # Используем цену с учетом промокода

    if not order_items:
        return send_message(chat_id, "Ошибка: товары не найдены или корзина пуста.")

    # СОХРАНЯЕМ В БД
    order_id = save_order_to_db(chat_id, user_name, order_items, total_price, contact)

    # ФОРМИРУЕМ ЧЕК ДЛЯ АДМИНА
    items_str = "\n".join([f"- {i['name']} x{i['qty']} = {i['price']*i['qty']} грн" for i in order_items])
    
    promo_code = payload.get("promo")
    promo_info = f"\n🎟️ Промокод: {promo_code}" if promo_code else ""
    
    admin_msg = (
        f"🔥 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\n\n"
        f"{items_str}\n"
        f"➖➖➖➖➖➖\n"
        f"💰 <b>Итого: {total_price} грн</b>{promo_info}\n\n"
        f"📂 <b>Клиент:</b>\n"
        f"{format_contact(contact)}\n"
        f"Telegram: @{user.get('username', 'net_nika')}"
    )

    send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML")
    
    # ОТВЕТ КЛИЕНТУ С ОПЦИЕЙ ОПЛАТЫ
    payment_link = generate_liqpay_link(
        order_id=order_id,
        amount=total_price,
        description=f"Заказ #{order_id} - Vape Market"
    )
    
    if payment_link:
        kb = {
            "inline_keyboard": [[
                {"text": "💳 Оплатить онлайн", "url": payment_link}
            ]]
        }
        send_message(chat_id, 
            f"✅ Спасибо! Заказ #{order_id} принят.\n\n"
            f"💰 Сумма: {total_price} грн\n\n"
            f"💳 Вы можете оплатить онлайн или дождаться звонка менеджера.",
            reply_markup=kb
        )
    else:
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
                    user_id = msg.get("from", {}).get("id", chat_id)  # ID пользователя
                    
                    # Отладка: логируем ID для проверки
                    if msg.get("text") == "/start":
                        logger.info(f"User ID: {user_id}, Chat ID: {chat_id}, Admin ID: {ADMIN_CHAT_ID}")
                        logger.info(f"Is admin: {user_id == ADMIN_CHAT_ID or chat_id == ADMIN_CHAT_ID}")
                    
                    if "web_app_data" in msg:
                        process_webapp_data(msg)
                    
                    elif "text" in msg:
                        txt = msg["text"]
                        if txt == "/start":
                            # Проверяем оба варианта ID
                            is_admin = (user_id == ADMIN_CHAT_ID) or (chat_id == ADMIN_CHAT_ID)
                            if is_admin:
                                # Админ-панель
                                kb = {
                                    "keyboard": [
                                        [{"text": "🛒 Открыть Shop", "web_app": {"url": WEBAPP_URL}}],
                                        [{"text": "📋 Заказы"}, {"text": "🆕 Новые заказы"}],
                                        [{"text": "📊 Статистика"}]
                                    ],
                                    "resize_keyboard": True
                                }
                                send_message(chat_id, "👑 Админ-панель\n\nВыбери действие:", reply_markup=kb)
                            else:
                                kb = {
                                    "keyboard": [[{"text": "🛒 Открыть Shop", "web_app": {"url": WEBAPP_URL}}]],
                                    "resize_keyboard": True
                                }
                                send_message(chat_id, "Привет! Жми кнопку ниже 👇", reply_markup=kb)
                        
                        elif txt == "/myid":
                            # Команда для получения своего ID (для всех)
                            send_message(chat_id, 
                                f"📱 Ваш ID:\n"
                                f"User ID: {user_id}\n"
                                f"Chat ID: {chat_id}\n\n"
                                f"Текущий Admin ID в коде: {ADMIN_CHAT_ID}\n\n"
                                f"Если вы админ, но панель не открывается, обновите ADMIN_CHAT_ID в bot.py на один из этих ID"
                            )
                        
                        elif (user_id == ADMIN_CHAT_ID) or (chat_id == ADMIN_CHAT_ID):
                            # Команда для получения своего ID
                            send_message(chat_id, 
                                f"📱 Ваш ID:\n"
                                f"User ID: {user_id}\n"
                                f"Chat ID: {chat_id}\n\n"
                                f"Текущий Admin ID: {ADMIN_CHAT_ID}"
                            )
                        
                        elif (user_id == ADMIN_CHAT_ID) or (chat_id == ADMIN_CHAT_ID):
                            # Админ-команды
                            if txt == "📋 Заказы" or txt.startswith("/orders"):
                                orders = get_orders(limit=10)
                                if not orders:
                                    send_message(chat_id, "Заказов пока нет")
                                else:
                                    msg_text = "📋 <b>Последние заказы:</b>\n\n"
                                    for o in orders:
                                        status_emoji = {"new": "🆕", "processing": "⚙️", "completed": "✅", "cancelled": "❌"}.get(o['status'], "📦")
                                        msg_text += f"{status_emoji} <b>#{o['id']}</b> - {o['total_price']} грн ({o['status']})\n"
                                        msg_text += f"   👤 {o['user_name']}\n"
                                        msg_text += f"   📅 {o['created_at']}\n\n"
                                    
                                    # Кнопки для управления
                                    kb = {
                                        "inline_keyboard": [
                                            [{"text": "🆕 Новые", "callback_data": "orders_new"}],
                                            [{"text": "⚙️ В работе", "callback_data": "orders_processing"}],
                                            [{"text": "✅ Завершенные", "callback_data": "orders_completed"}]
                                        ]
                                    }
                                    send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)
                            
                            elif txt == "🆕 Новые заказы":
                                orders = get_orders(status="new", limit=20)
                                if not orders:
                                    send_message(chat_id, "Новых заказов нет")
                                else:
                                    for o in orders:
                                        items_str = "\n".join([f"- {i['name']} x{i['qty']}" for i in o['items']])
                                        msg_text = (
                                            f"🆕 <b>Заказ #{o['id']}</b>\n\n"
                                            f"{items_str}\n"
                                            f"💰 <b>{o['total_price']} грн</b>\n\n"
                                            f"👤 {o['contact'].get('name')}\n"
                                            f"📞 {o['contact'].get('phone')}\n"
                                            f"🏠 {o['contact'].get('address')}\n\n"
                                        )
                                        kb = {
                                            "inline_keyboard": [
                                                [
                                                    {"text": "✅ Взять в работу", "callback_data": f"status_{o['id']}_processing"},
                                                    {"text": "✅ Завершить", "callback_data": f"status_{o['id']}_completed"}
                                                ],
                                                [{"text": "❌ Отменить", "callback_data": f"status_{o['id']}_cancelled"}]
                                            ]
                                        }
                                        send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)
                            
                            elif txt == "📊 Статистика":
                                conn = sqlite3.connect(DB_PATH)
                                c = conn.cursor()
                                c.execute('SELECT COUNT(*) FROM orders')
                                total = c.fetchone()[0]
                                c.execute('SELECT COUNT(*) FROM orders WHERE status = "new"')
                                new_count = c.fetchone()[0]
                                c.execute('SELECT SUM(total_price) FROM orders WHERE status != "cancelled"')
                                revenue = c.fetchone()[0] or 0
                                conn.close()
                                
                                msg_text = (
                                    f"📊 <b>Статистика</b>\n\n"
                                    f"📦 Всего заказов: {total}\n"
                                    f"🆕 Новых: {new_count}\n"
                                    f"💰 Выручка: {revenue:.2f} грн"
                                )
                                send_message(chat_id, msg_text, parse_mode="HTML")
                            
                            elif txt.startswith("/order "):
                                # Просмотр конкретного заказа
                                try:
                                    order_id = int(txt.split()[1])
                                    order = get_order(order_id)
                                    if order:
                                        items_str = "\n".join([f"- {i['name']} x{i['qty']} = {i['price']*i['qty']} грн" for i in order['items']])
                                        msg_text = (
                                            f"📦 <b>Заказ #{order['id']}</b>\n\n"
                                            f"{items_str}\n"
                                            f"➖➖➖➖➖➖\n"
                                            f"💰 <b>Итого: {order['total_price']} грн</b>\n\n"
                                            f"📂 <b>Клиент:</b>\n"
                                            f"{format_contact(order['contact'])}\n"
                                            f"📅 {order['created_at']}\n"
                                            f"📊 Статус: {order['status']}"
                                        )
                                        kb = {
                                            "inline_keyboard": [
                                                [
                                                    {"text": "✅ Взять в работу", "callback_data": f"status_{order['id']}_processing"},
                                                    {"text": "✅ Завершить", "callback_data": f"status_{order['id']}_completed"}
                                                ],
                                                [{"text": "❌ Отменить", "callback_data": f"status_{order['id']}_cancelled"}]
                                            ]
                                        }
                                        send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)
                                    else:
                                        send_message(chat_id, "Заказ не найден")
                                except:
                                    send_message(chat_id, "Использование: /order <номер>")
                
                elif "callback_query" in upd:
                    # Обработка inline кнопок
                    query = upd["callback_query"]
                    query_id = query["id"]
                    data = query["data"]
                    chat_id = query.get("message", {}).get("chat", {}).get("id", 0)
                    user_id_from_query = query["from"]["id"]
                    
                    if (user_id_from_query != ADMIN_CHAT_ID) and (chat_id != ADMIN_CHAT_ID):
                        requests.post(API_URL + "answerCallbackQuery", json={"callback_query_id": query_id, "text": "Только для админа"})
                        continue
                    
                    if data.startswith("status_"):
                        # Изменение статуса заказа
                        parts = data.split("_")
                        order_id = int(parts[1])
                        new_status = parts[2]
                        
                        if update_order_status(order_id, new_status):
                            order = get_order(order_id)
                            if order:
                                # Уведомляем клиента
                                status_messages = {
                                    "processing": "⚙️ Ваш заказ #{} взят в работу!",
                                    "completed": "✅ Заказ #{} выполнен! Спасибо за покупку!",
                                    "cancelled": "❌ Заказ #{} отменен. Если есть вопросы, свяжитесь с нами."
                                }
                                msg_to_user = status_messages.get(new_status, "📦 Статус заказа #{} изменен")
                                send_message(order['user_id'], msg_to_user.format(order_id))
                            
                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": f"Статус изменен на {new_status}"
                            })
                            
                            # Обновляем сообщение
                            status_emoji = {"new": "🆕", "processing": "⚙️", "completed": "✅", "cancelled": "❌"}.get(new_status, "📦")
                            requests.post(API_URL + "editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": query["message"]["message_id"],
                                "text": f"{status_emoji} Статус заказа #{order_id} изменен на: {new_status}",
                                "parse_mode": "HTML"
                            })
                        else:
                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": "Ошибка обновления"
                            })
                    
                    elif data.startswith("orders_"):
                        status = data.split("_")[1]
                        orders = get_orders(status=status if status != "all" else None, limit=10)
                        if not orders:
                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": "Заказов нет"
                            })
                        else:
                            msg_text = f"📋 <b>Заказы ({status}):</b>\n\n"
                            for o in orders[:5]:
                                msg_text += f"#{o['id']} - {o['total_price']} грн\n"
                            requests.post(API_URL + "editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": query["message"]["message_id"],
                                "text": msg_text,
                                "parse_mode": "HTML"
                            })
                            requests.post(API_URL + "answerCallbackQuery", json={"callback_query_id": query_id})

        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
