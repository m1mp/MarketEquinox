import os
import json
import time
import logging
import sqlite3
import hashlib
import base64
from datetime import datetime
from typing import Dict, Any, List

import requests

# === Config ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "979000473"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://market-equinox.vercel.app/")

LIQPAY_PUBLIC_KEY = os.getenv("LIQPAY_PUBLIC_KEY", "your_public_key")
LIQPAY_PRIVATE_KEY = os.getenv("LIQPAY_PRIVATE_KEY", "your_private_key")
LIQPAY_SANDBOX = os.getenv("LIQPAY_SANDBOX", "true").lower() == "true"
LIQPAY_SERVER_URL = os.getenv("LIQPAY_SERVER_URL", WEBAPP_URL.rstrip('/') + "/payment_callback")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON_PATH = os.path.join(BASE_DIR, "products.json")
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "shop.db"))

# === Database ===
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
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
        """
    )
    try:
        c.execute('ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT "pending"')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def save_order_to_db(user_id: int, user_name: str, items: List[Dict[str, Any]], total_price: float, contact: Dict[str, Any]) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO orders (user_id, user_name, items_json, total_price, contact_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            user_name,
            json.dumps(items, ensure_ascii=False),
            total_price,
            json.dumps(contact, ensure_ascii=False),
        ),
    )
    order_id = c.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_orders(status: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if status:
        c.execute('SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?', (status, limit))
    else:
        c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()

    columns = [
        'id', 'user_id', 'user_name', 'items_json', 'total_price',
        'contact_json', 'status', 'payment_status', 'created_at'
    ]
    orders: List[Dict[str, Any]] = []
    for row in rows:
        order = dict(zip(columns, row))
        order['items'] = json.loads(order['items_json'])
        order['contact'] = json.loads(order['contact_json'])
        orders.append(order)
    return orders


def update_order_status(order_id: int, new_status: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE orders SET status = ? WHERE id = ?', (new_status, order_id))
    conn.commit()
    changed = c.rowcount > 0
    conn.close()
    return changed


def get_order(order_id: int) -> Dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    columns = [
        'id', 'user_id', 'user_name', 'items_json', 'total_price',
        'contact_json', 'status', 'payment_status', 'created_at'
    ]
    order = dict(zip(columns, row))
    order['items'] = json.loads(order['items_json'])
    order['contact'] = json.loads(order['contact_json'])
    return order


# === Products ===
PRODUCTS: List[Dict[str, Any]] = []
PRODUCTS_BY_ID: Dict[int, Dict[str, Any]] = {}


def load_products() -> None:
    global PRODUCTS, PRODUCTS_BY_ID
    try:
        path = PRODUCTS_JSON_PATH if os.path.exists(PRODUCTS_JSON_PATH) else os.path.join(os.getcwd(), "products.json")
        if not os.path.exists(path):
            logger.error("products.json not found")
            PRODUCTS, PRODUCTS_BY_ID = [], {}
            return
        with open(path, "r", encoding="utf-8") as f:
            PRODUCTS = json.load(f)
        PRODUCTS_BY_ID = {int(p["id"]): p for p in PRODUCTS}
        logger.info("Products loaded: %s", len(PRODUCTS))
    except Exception as e:
        logger.exception("Failed to load products: %s", e)


def get_product(pid: int):
    return PRODUCTS_BY_ID.get(pid)


def find_option(product: Dict[str, Any] | None, opt_id: Any):
    if not product or not opt_id:
        return None
    for opt in product.get("options", []):
        if str(opt.get("id")) == str(opt_id):
            return opt
    return None


# === Telegram helpers ===
def send_message(chat_id: int, text: str, parse_mode: str | None = None, reply_markup: Dict[str, Any] | None = None) -> None:
    data: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(API_URL + "sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error("Send Error: %s", e)


def format_contact(c: Dict[str, Any]) -> str:
    if not c:
        return "Нет контактных данных"
    return (
        f"Имя: {c.get('name')}\n"
        f"Телефон: {c.get('phone')}\n"
        f"Адрес: {c.get('address')}\n"
        f"Комментарий: {c.get('comment')}"
    )


# === LiqPay ===
def generate_liqpay_link(order_id: int, amount: float, description: str, result_url: str | None = None) -> str | None:
    if LIQPAY_PUBLIC_KEY == "your_public_key":
        return None
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
        "server_url": LIQPAY_SERVER_URL,
    }
    data_str = json.dumps(data, separators=(',', ':'))
    data_encoded = base64.b64encode(data_str.encode('utf-8')).decode('utf-8')
    signature_string = LIQPAY_PRIVATE_KEY + data_encoded + LIQPAY_PRIVATE_KEY
    signature = base64.b64encode(hashlib.sha1(signature_string.encode('utf-8')).digest()).decode('utf-8')
    return f"https://www.liqpay.ua/api/3/checkout?data={data_encoded}&signature={signature}"


def verify_liqpay_signature(data: str, signature: str) -> bool:
    expected_signature = base64.b64encode(
        hashlib.sha1((LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode('utf-8')).digest()
    ).decode('utf-8')
    return expected_signature == signature


# === WebApp data ===
def process_webapp_data(message: Dict[str, Any]):
    chat_id = message["chat"]["id"]
    try:
        payload = json.loads(message["web_app_data"]["data"])
    except Exception:
        return send_message(chat_id, "Ошибка данных WebApp")

    action = payload.get("action")
    contact = payload.get("contact", {})
    user = message.get("from", {})
    user_name = f"{user.get('first_name','')} {user.get('last_name','')}".strip()

    order_items: List[Dict[str, Any]] = []
    total_price = 0.0

    if action == "buy":
        pid = int(payload.get("productId", 0))
        oid = payload.get("optionId")
        product = get_product(pid)
        if product:
            opt = find_option(product, oid)
            name = product["name"] + (f" ({opt['name']})" if opt else "")
            price = product["price"]
            order_items.append({"name": name, "price": price, "qty": 1})
            total_price += price
    elif action == "cart_checkout":
        for item in payload.get("items", []):
            pid = int(item.get("productId") or item.get("id", 0))
            oid = item.get("optionId")
            qty = item.get("qty", 1)
            product = get_product(pid)
            if product:
                opt = find_option(product, oid)
                name = product["name"] + (f" ({opt['name']})" if opt else "")
                price = product["price"]
                order_items.append({"name": name, "price": price, "qty": qty})
                total_price += price * qty
        final_price = payload.get("totalPrice")
        if final_price is not None:
            total_price = float(final_price)

    if not order_items:
        return send_message(chat_id, "Корзина пуста или товар не найден")

    order_id = save_order_to_db(chat_id, user_name, order_items, total_price, contact)

    items_str = "\n".join([f"- {i['name']} x{i['qty']} = {i['price']*i['qty']} грн" for i in order_items])
    promo_code = payload.get("promo")
    promo_info = f"\nПромокод: {promo_code}" if promo_code else ""

    admin_msg = (
        f"🛒 <b>Новый заказ #{order_id}</b>\n\n"
        f"{items_str}\n"
        f"----------------\n"
        f"Итого: <b>{total_price} грн</b>{promo_info}\n\n"
        f"Контакты:\n{format_contact(contact)}\n"
        f"Telegram: @{user.get('username', 'net_nika')}"
    )
    send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML")

    payment_link = generate_liqpay_link(order_id, total_price, f"Заказ #{order_id} - Vape Market")
    if payment_link:
        kb = {"inline_keyboard": [[{"text": "Оплатить картой", "url": payment_link}]]}
        send_message(
            chat_id,
            f"Спасибо! Заказ #{order_id} оформлен.\n\nСумма: {total_price} грн\n\nОплатите заказ по ссылке ниже.",
            reply_markup=kb,
        )
    else:
        send_message(chat_id, f"Спасибо! Заказ #{order_id} оформлен. Оплата будет уточнена дополнительно.")


# === Main loop ===
def main():
    init_db()
    load_products()
    logger.info("Bot started...")

    offset = None
    while True:
        try:
            params = {"timeout": 50, "offset": offset}
            resp = requests.get(API_URL + "getUpdates", params=params, timeout=60)
            data = resp.json()
            if not data.get("ok"):
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    user_id = msg.get("from", {}).get("id", chat_id)

                    if "web_app_data" in msg:
                        process_webapp_data(msg)
                        continue

                    if "text" in msg:
                        txt = msg["text"]

                        if txt in ("/start", "/myid"):
                            logger.info("Command %s from user %s chat %s", txt, user_id, chat_id)
                            logger.info("Admin? %s", user_id == ADMIN_CHAT_ID or chat_id == ADMIN_CHAT_ID)

                        if txt == "/start":
                            is_admin = (user_id == ADMIN_CHAT_ID) or (chat_id == ADMIN_CHAT_ID)
                            if is_admin:
                                kb = {
                                    "keyboard": [
                                        [{"text": "Открыть Shop", "web_app": {"url": WEBAPP_URL}}],
                                        [{"text": "Список заказов"}, {"text": "Новые заказы"}],
                                        [{"text": "Статистика"}],
                                    ],
                                    "resize_keyboard": True,
                                }
                                send_message(chat_id, "Админ-панель. Выберите действие:", reply_markup=kb)
                            else:
                                kb = {
                                    "keyboard": [[{"text": "Открыть Shop", "web_app": {"url": WEBAPP_URL}}]],
                                    "resize_keyboard": True,
                                }
                                send_message(chat_id, "Привет! Открой магазин по кнопке ниже.", reply_markup=kb)
                            continue

                        if txt == "/myid":
                            send_message(
                                chat_id,
                                f"Твой ID:\nUser ID: {user_id}\nChat ID: {chat_id}\n\nТекущий Admin ID в коде: {ADMIN_CHAT_ID}\n\n"
                                "Если ты админ и панель не открывается, обнови ADMIN_CHAT_ID в bot.py",
                            )
                            continue

                        if (user_id == ADMIN_CHAT_ID) or (chat_id == ADMIN_CHAT_ID):
                            if txt == "Список заказов" or txt.startswith("/orders"):
                                orders = get_orders(limit=10)
                                if not orders:
                                    send_message(chat_id, "Заказы не найдены")
                                else:
                                    msg_text = "<b>Последние заказы:</b>\n\n"
                                    for o in orders:
                                        status_emoji = {"new": "🆕", "processing": "⏳", "completed": "✅", "cancelled": "❌"}.get(o['status'], "ℹ️")
                                        msg_text += f"{status_emoji} <b>#{o['id']}</b> - {o['total_price']} грн ({o['status']})\n"
                                        msg_text += f"   Имя: {o['user_name']}\n"
                                        msg_text += f"   Время: {o['created_at']}\n\n"
                                    kb = {
                                        "inline_keyboard": [
                                            [{"text": "Новые", "callback_data": "orders_new"}],
                                            [{"text": "В обработке", "callback_data": "orders_processing"}],
                                            [{"text": "Завершённые", "callback_data": "orders_completed"}],
                                        ]
                                    }
                                    send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)

                            elif txt == "Новые заказы":
                                orders = get_orders(status="new", limit=20)
                                if not orders:
                                    send_message(chat_id, "Новых заказов нет")
                                else:
                                    for o in orders:
                                        items_str = "\n".join([f"- {i['name']} x{i['qty']}" for i in o['items']])
                                        msg_text = (
                                            f"🆕 <b>Заказ #{o['id']}</b>\n\n{items_str}\nИтого: <b>{o['total_price']} грн</b>\n\n"
                                            f"Имя: {o['contact'].get('name')}\nТелефон: {o['contact'].get('phone')}\nАдрес: {o['contact'].get('address')}\n"
                                        )
                                        kb = {
                                            "inline_keyboard": [
                                                [
                                                    {"text": "В обработке", "callback_data": f"status_{o['id']}_processing"},
                                                    {"text": "Завершён", "callback_data": f"status_{o['id']}_completed"},
                                                ],
                                                [{"text": "Отменить", "callback_data": f"status_{o['id']}_cancelled"}],
                                            ]
                                        }
                                        send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)

                            elif txt == "Статистика":
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
                                    f"Статистика\n\nВсего заказов: {total}\nНовые: {new_count}\nВыручка: {revenue:.2f} грн"
                                )
                                send_message(chat_id, msg_text, parse_mode="HTML")

                            elif txt.startswith("/order "):
                                try:
                                    oid = int(txt.split()[1])
                                except Exception:
                                    send_message(chat_id, "Используй: /order <id>")
                                    continue
                                order = get_order(oid)
                                if order:
                                    items_str = "\n".join([f"- {i['name']} x{i['qty']} = {i['price']*i['qty']} грн" for i in order['items']])
                                    msg_text = (
                                        f"ℹ️ <b>Заказ #{order['id']}</b>\n\n{items_str}\n----------------\n"
                                        f"Итого: <b>{order['total_price']} грн</b>\n\nКонтакты:\n{format_contact(order['contact'])}\n"
                                        f"Создан: {order['created_at']}\nСтатус: {order['status']}"
                                    )
                                    kb = {
                                        "inline_keyboard": [
                                            [
                                                {"text": "В обработке", "callback_data": f"status_{order['id']}_processing"},
                                                {"text": "Завершён", "callback_data": f"status_{order['id']}_completed"},
                                            ],
                                            [{"text": "Отменить", "callback_data": f"status_{order['id']}_cancelled"}],
                                        ]
                                    }
                                    send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=kb)
                                else:
                                    send_message(chat_id, "Заказ не найден")

                            else:
                                send_message(chat_id, "Команды: Список заказов, Новые заказы, Статистика, /order <id>")

                elif "callback_query" in upd:
                    query = upd["callback_query"]
                    query_id = query["id"]
                    data_cb = query["data"]
                    chat_id = query.get("message", {}).get("chat", {}).get("id", 0)
                    user_id_from_query = query["from"]["id"]

                    if (user_id_from_query != ADMIN_CHAT_ID) and (chat_id != ADMIN_CHAT_ID):
                        requests.post(API_URL + "answerCallbackQuery", json={"callback_query_id": query_id, "text": "Нет прав"})
                        continue

                    if data_cb.startswith("status_"):
                        parts = data_cb.split("_")
                        order_id = int(parts[1])
                        new_status = parts[2]

                        if update_order_status(order_id, new_status):
                            order = get_order(order_id)
                            if order:
                                status_messages = {
                                    "processing": "Заказ #{} принят в обработку",
                                    "completed": "Заказ #{} выполнен!",
                                    "cancelled": "Заказ #{} отменён. Свяжитесь с поддержкой, если нужна помощь.",
                                }
                                msg_to_user = status_messages.get(new_status, "Статус заказа #{} обновлён")
                                send_message(order['user_id'], msg_to_user.format(order_id))

                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": f"Статус обновлён на {new_status}",
                            })

                            status_emoji = {"new": "🆕", "processing": "⏳", "completed": "✅", "cancelled": "❌"}.get(new_status, "ℹ️")
                            requests.post(API_URL + "editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": query["message"]["message_id"],
                                "text": f"{status_emoji} Статус заказа #{order_id} теперь: {new_status}",
                                "parse_mode": "HTML",
                            })
                        else:
                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": "Не удалось обновить статус",
                            })

                    elif data_cb.startswith("orders_"):
                        status = data_cb.split("_")[1]
                        orders = get_orders(status=None if status == "all" else status, limit=10)
                        if not orders:
                            requests.post(API_URL + "answerCallbackQuery", json={
                                "callback_query_id": query_id,
                                "text": "Заказы не найдены",
                            })
                        else:
                            msg_text = f"<b>Заказы ({status}):</b>\n\n"
                            for o in orders[:5]:
                                msg_text += f"#{o['id']} - {o['total_price']} грн\n"
                            requests.post(API_URL + "editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": query["message"]["message_id"],
                                "text": msg_text,
                                "parse_mode": "HTML",
                            })
                            requests.post(API_URL + "answerCallbackQuery", json={"callback_query_id": query_id})

        except Exception as e:
            logger.error("Error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
