"""
Простой сервер для обработки платежных callback от LiqPay
Запустите отдельно: python payment_handler.py
Или используйте webhook в вашем хостинге
"""
import os
import json
import base64
import hashlib
import sqlite3
import logging
from flask import Flask, request, jsonify

# Настройки (должны совпадать с bot.py)
LIQPAY_PRIVATE_KEY = os.getenv("LIQPAY_PRIVATE_KEY", "your_private_key")
DB_PATH = os.getenv("DB_PATH", "shop.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_liqpay_signature(data, signature):
    """Проверяет подпись от LiqPay"""
    expected_signature = base64.b64encode(
        hashlib.sha1((LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode('utf-8')).digest()
    ).decode('utf-8')
    return expected_signature == signature

def update_order_payment_status(order_id, status):
    """Обновляет статус оплаты заказа"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE orders SET payment_status = ? WHERE id = ?', (status, order_id))
    conn.commit()
    conn.close()

def send_telegram_message(chat_id, text):
    """Отправляет сообщение через Telegram API"""
    import requests
    API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    try:
        requests.post(API_URL + "sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

@app.route('/payment_callback', methods=['POST'])
def payment_callback():
    """Обработка callback от LiqPay"""
    try:
        data = request.form.get('data')
        signature = request.form.get('signature')
        
        if not data or not signature:
            return jsonify({"error": "Missing data or signature"}), 400
        
        # Проверяем подпись
        if not verify_liqpay_signature(data, signature):
            logger.warning("Invalid signature")
            return jsonify({"error": "Invalid signature"}), 400
        
        # Декодируем данные
        decoded_data = base64.b64decode(data).decode('utf-8')
        payment_data = json.loads(decoded_data)
        
        order_id = int(payment_data.get('order_id', 0))
        status = payment_data.get('status')
        amount = payment_data.get('amount')
        
        logger.info(f"Payment callback: order_id={order_id}, status={status}")
        
        # Обновляем статус оплаты
        if status == 'success':
            update_order_payment_status(order_id, 'paid')
            
            # Уведомляем админа
            if ADMIN_CHAT_ID:
                send_telegram_message(
                    ADMIN_CHAT_ID,
                    f"💳 Оплачен заказ #{order_id}\nСумма: {amount} грн"
                )
            
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

