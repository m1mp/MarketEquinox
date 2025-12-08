import os
import json
import time
import logging
from typing import Optional, Dict, Any, List

import requests

# ========= НАСТРОЙКИ =========
# ВСТАВЬ СЮДА СВОЙ ТОКЕН И АДМИН-АЙДИ
TELEGRAM_BOT_TOKEN = "8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0"
ADMIN_CHAT_ID = 979000473  # твой Telegram ID (куда будут прилетать заказы)

# URL твоего WebApp на GitHub Pages
WEBAPP_URL = "https://market-equinox.vercel.app/"

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

# ========= ЛОГИ =========

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= ЗАГРУЗКА ТОВАРОВ =========

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON_PATH = os.path.join(BASE_DIR, "webapp", "products.json")

PRODUCTS: List[Dict[str, Any]] = []
PRODUCTS_BY_ID: Dict[int, Dict[str, Any]] = {}


def load_products() -> None:
    global PRODUCTS, PRODUCTS_BY_ID
    try:
        with open(PRODUCTS_JSON_PATH, "r", encoding="utf-8") as f:
            PRODUCTS = json.load(f)
        PRODUCTS_BY_ID = {int(p["id"]): p for p in PRODUCTS}
        logger.info("Products loaded: %d items", len(PRODUCTS))
    except Exception as e:
        logger.exception("Failed to load products.json: %s", e)
        PRODUCTS = []
        PRODUCTS_BY_ID = {}


def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    return PRODUCTS_BY_ID.get(product_id)


def has_options(product: Dict[str, Any]) -> bool:
    return isinstance(product.get("options"), list) and len(product["options"]) > 0


def find_option(product: Dict[str, Any], option_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not has_options(product) or not option_id:
        return None
    for opt in product["options"]:
        if str(opt.get("id")) == str(option_id):
            return opt
    return None


# ========= ХЕЛПЕРЫ =========

def send_message(chat_id: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None):
    data: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        data["parse_mode"] = parse_mode
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        r = requests.post(API_URL + "sendMessage", data=data, timeout=10)
        if not r.ok:
            logger.warning("sendMessage failed: %s", r.text)
    except Exception as e:
        logger.exception("sendMessage exception: %s", e)


def format_product_option_line(
    product: Dict[str, Any],
    option: Optional[Dict[str, Any]],
    qty: Optional[int] = None,
) -> str:
    name = product.get("name", f"ID {product.get('id')}")
    price = product.get("price", 0)

    option_label = product.get("optionLabel") or "Вариант"
    option_part = ""
    if option is not None:
        option_name = option.get("name")
        if option_name:
            option_part = f" ({option_label}: {option_name})"

    if qty is None or qty <= 0:
        return f"- {name}{option_part} — {price} грн"

    line_total = price * qty
    return f"- {name}{option_part} — {qty} шт. × {price} = {line_total} грн"


def build_user_title(user: dict) -> str:
    if not user:
        return "Неизвестный пользователь"
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    username = user.get("username")

    parts = []
    if first_name:
        parts.append(first_name)
    if last_name:
        parts.append(last_name)
    title = " ".join(parts) if parts else "Без имени"
    if username:
        title += f" (@{username})"
    return title


def format_contact_block(contact: Optional[Dict[str, Any]]) -> str:
    """
    Форматируем блок с контактными данными, которые пришли из WebApp.
    contact:
      {
        "name": "...",
        "phone": "...",
        "preferred": "telegram" | "phone" | "whatsapp",
        "city": "...",
        "delivery": "...",
        "address": "...",
        "comment": "..."
      }
    """
    if not isinstance(contact, dict):
        return "Данные формы не переданы."

    name = contact.get("name") or "—"
    phone = contact.get("phone") or "—"
    preferred = contact.get("preferred") or "—"
    city = contact.get("city") or "—"
    delivery = contact.get("delivery") or "—"
    address = contact.get("address") or "—"
    comment = contact.get("comment") or "—"

    if preferred == "telegram":
        preferred_human = "Написать в Telegram"
    elif preferred == "phone":
        preferred_human = "Позвонить"
    elif preferred == "whatsapp":
        preferred_human = "Написать в WhatsApp"
    else:
        preferred_human = preferred

    lines = [
        f"Имя: {name}",
        f"Телефон: {phone}",
        f"Способ связи: {preferred_human}",
        f"Город: {city}",
        f"Доставка: {delivery}",
        f"Адрес / отделение: {address}",
        f"Комментарий: {comment}",
    ]
    return "\n".join(lines)


# ========= ОБРАБОТКА КОМАНД И СООБЩЕНИЙ =========

def handle_start(message: dict):
    chat_id = message["chat"]["id"]

    webapp_button = {
        "text": "🛒 Открыть магазин",
        "web_app": {"url": WEBAPP_URL},
    }
    support_button = {
        "text": "✉️ Написать в поддержку",
    }

    reply_markup = {
      "keyboard": [
          [webapp_button],
          [support_button],
      ],
      "resize_keyboard": True,
      "one_time_keyboard": False,
    }

    send_message(
        chat_id,
        "Привет! Это Vape Market.\n\n"
        "Нажми «🛒 Открыть магазин», чтобы посмотреть каталог и оформить заказ.",
        reply_markup=reply_markup,
    )


def handle_text(message: dict):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if "поддерж" in text.lower():
        send_message(
            chat_id,
            "Для связи с поддержкой напиши, пожалуйста, сюда: "
            "@your_support_username (замени на свой) 😉"
        )
    else:
        send_message(
            chat_id,
            "Чтобы открыть каталог, нажми кнопку «🛒 Открыть магазин» ниже."
        )


# ========= ОБРАБОТКА ДАННЫХ ИЗ WEBAPP =========

def handle_webapp_data(message: dict):
    chat_id = message["chat"]["id"]
    from_user = message.get("from") or {}

    web_app_data = message.get("web_app_data")
    if not web_app_data:
        return

    data_str = web_app_data.get("data") or ""
    logger.info("web_app_data from %s: %s", from_user.get("id"), data_str)

    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError:
        send_message(chat_id, "Ошибка: не удалось разобрать данные из WebApp 😔")
        return

    action = payload.get("action")
    if action == "buy":
        process_buy(payload, message, from_user)
    elif action == "cart_checkout":
        process_cart_checkout(payload, message, from_user)
    else:
        send_message(chat_id, "Неизвестное действие из WebApp.")


def process_buy(payload: Dict[str, Any], message: dict, from_user: dict):
    chat_id = message["chat"]["id"]

    product_id = payload.get("productId")
    option_id = payload.get("optionId")
    contact = payload.get("contact")  # может быть None

    if product_id is None:
        send_message(chat_id, "Ошибка: не передан ID товара.")
        return

    try:
        product_id = int(product_id)
    except ValueError:
        send_message(chat_id, "Ошибка: некорректный ID товара.")
        return

    product = get_product(product_id)
    if not product:
        send_message(chat_id, "Ошибка: товар не найден.")
        return

    option = find_option(product, option_id) if option_id else None

    user_title = build_user_title(from_user)
    user_id_line = f"ID пользователя: {from_user.get('id')}" if from_user.get("id") else "ID пользователя неизвестен"

    contact_block = format_contact_block(contact)

    admin_text = (
        "🆕 <b>Новый заказ (один товар)</b>\n\n"
        f"👤 {user_title}\n"
        f"{user_id_line}\n\n"
        f"{format_product_option_line(product, option, qty=1)}\n\n"
        f"<b>Контактные данные:</b>\n"
        f"{contact_block}"
    )

    send_message(ADMIN_CHAT_ID, admin_text, parse_mode="HTML")

    send_message(
        chat_id,
        "Заявка отправлена! 🙌\n"
        "Скоро с тобой свяжется продавец для уточнения деталей."
    )


def process_cart_checkout(payload: Dict[str, Any], message: dict, from_user: dict):
    chat_id = message["chat"]["id"]
    items = payload.get("items")
    contact = payload.get("contact")  # может быть None

    if not isinstance(items, list) or not items:
        send_message(chat_id, "Корзина пуста или данные повреждены.")
        return

    lines = []
    total_sum = 0

    for idx, item in enumerate(items, start=1):
        product_id = item.get("productId")
        option_id = item.get("optionId")
        qty = item.get("qty", 1)

        if product_id is None:
            continue

        try:
            product_id = int(product_id)
        except ValueError:
            continue

        try:
            qty = int(qty)
        except Exception:
            qty = 1

        if qty <= 0:
            continue

        product = get_product(product_id)
        if not product:
            continue

        option = find_option(product, option_id) if option_id else None
        price = product.get("price", 0)
        line_total = price * qty
        total_sum += line_total

        line_text = format_product_option_line(product, option, qty=qty)
        lines.append(f"{idx}) {line_text}")

    if not lines:
        send_message(chat_id, "Все товары из корзины недоступны или удалены.")
        return

    user_title = build_user_title(from_user)
    user_id_line = f"ID пользователя: {from_user.get('id')}" if from_user.get("id") else "ID пользователя неизвестен"

    contact_block = format_contact_block(contact)

    admin_text = (
        "🆕 <b>Новый заказ (корзина)</b>\n\n"
        f"👤 {user_title}\n"
        f"{user_id_line}\n\n"
        + "\n".join(lines)
        + f"\n\n<b>Итого: {total_sum} грн</b>\n\n"
        f"<b>Контактные данные:</b>\n"
        f"{contact_block}"
    )

    send_message(ADMIN_CHAT_ID, admin_text, parse_mode="HTML")

    send_message(
        chat_id,
        "Заявка по корзине отправлена! 🛒\n"
        "Скоро с тобой свяжется продавец для подтверждения заказа."
    )


# ========= ПОЛЛИНГ ОБНОВЛЕНИЙ =========

def get_updates(offset: Optional[int] = None, timeout: int = 50) -> List[dict]:
    params: Dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(API_URL + "getUpdates", params=params, timeout=timeout + 5)
        if not r.ok:
            logger.warning("getUpdates failed: %s", r.text)
            return []
        data = r.json()
        if not data.get("ok"):
            logger.warning("getUpdates not ok: %s", data)
            return []
        return data.get("result", [])
    except Exception as e:
        logger.exception("getUpdates exception: %s", e)
        return []


def process_update(update: dict):
    if "message" not in update:
        return

    message = update["message"]

    # web_app_data
    if "web_app_data" in message:
        handle_webapp_data(message)
        return

    text = message.get("text") or ""

    # команды
    if text.startswith("/start") or text.startswith("/help"):
        handle_start(message)
    elif text:
        handle_text(message)


def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("PASTE_"):
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в bot.py")

    load_products()
    logger.info("Bot started with raw Telegram API polling")

    offset = None

    while True:
        updates = get_updates(offset=offset, timeout=50)
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                process_update(upd)
            except Exception as e:
                logger.exception("Error processing update: %s", e)

        time.sleep(1)


if __name__ == "__main__":
    main()
