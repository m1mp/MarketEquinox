"""
Webhook обработчик LiqPay
Запуск: python payment_handler.py
"""
import os
import json
import base64
import hashlib
import sqlite3
import logging
from flask import Flask, request, jsonify

LIQPAY_PRIVATE_KEY = os.getenv("LIQPAY_PRIVATE_KEY", "your_private_key")
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "shop.db"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_liqpay_signature(data: str, signature: str) -> bool:
    expected_signature = base64.b64encode(
        hashlib.sha1((LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode('utf-8')).digest()
    ).decode('utf-8')
    return expected_signature == signature


def update_order_payment_status(order_id: int, status: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE orders SET payment_status = ? WHERE id = ?', (status, order_id))
    conn.commit()
    conn.close()


def get_order(order_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, total_price, payment_status FROM orders WHERE id = ?', (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "total_price": row[1], "payment_status": row[2]}


def send_telegram_message(chat_id: int, text: str) -> None:
    import requests
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    try:
        requests.post(api_url + "sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


@app.route('/payment_callback', methods=['POST'])
def payment_callback():
    """Принимает callback от LiqPay"""
    try:
        data = request.form.get('data')
        signature = request.form.get('signature')

        if not data or not signature:
            return jsonify({"error": "Missing data or signature"}), 400

        if not verify_liqpay_signature(data, signature):
            logger.warning("Invalid signature")
            return jsonify({"error": "Invalid signature"}), 400

        decoded_data = base64.b64decode(data).decode('utf-8')
        payment_data = json.loads(decoded_data)

        order_id = int(payment_data.get('order_id', 0))
        status = payment_data.get('status')
        amount = payment_data.get('amount')
        currency = (payment_data.get('currency') or '').upper()

        order = get_order(order_id)
        if not order:
            logger.warning("Order not found: %s", order_id)
            return jsonify({"error": "order not found"}), 404

        if amount is None:
            return jsonify({"error": "amount missing"}), 400
        try:
            amount_val = float(amount)
        except Exception:
            return jsonify({"error": "invalid amount"}), 400

        if abs(float(order['total_price']) - amount_val) > 0.01:
            logger.warning("Amount mismatch for order %s: expected %s got %s", order_id, order['total_price'], amount_val)
            return jsonify({"error": "amount mismatch"}), 400

        if currency and currency != 'UAH':
            logger.warning("Currency mismatch for order %s: %s", order_id, currency)
            return jsonify({"error": "currency mismatch"}), 400

        if status == 'success':
            if order.get('payment_status') == 'paid':
                return jsonify({"status": "ok"})

            update_order_payment_status(order_id, 'paid')

            if ADMIN_CHAT_ID:
                send_telegram_message(ADMIN_CHAT_ID, f"✅ Оплата заказа #{order_id}\nСумма: {amount_val} UAH")

            return jsonify({"status": "ok"})
        elif status == 'failure':
            update_order_payment_status(order_id, 'failed')
            return jsonify({"status": "ok"})
        else:
            return jsonify({"status": "ok"})

    except Exception as e:
        logger.exception(f"Payment callback error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
