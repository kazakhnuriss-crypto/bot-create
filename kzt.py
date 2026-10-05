
import os
import threading
import io
import secrets

import telebot
from telebot import types
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

MIN_STARS = 50
MAX_STARS = 10000
RATE = 8.8

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN және ADMIN_ID мәндерін .env файлына енгізіңіз")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

orders = {}

@app.get("/")
def home():
    return "Stars Shop API is running"

@app.post("/api/order")
def create_order():
    amount = request.form.get("amount", type=int)
    user_id = request.form.get("telegram_user_id", type=str)
    username = request.form.get("telegram_username", "")
    receipt = request.files.get("receipt")

    if amount is None or not MIN_STARS <= amount <= MAX_STARS:
        return jsonify(error="Invalid Stars amount"), 400

    if not user_id or not user_id.isdigit():
        return jsonify(error="Open the Mini App in Telegram"), 400

    if not receipt or not receipt.filename.lower().endswith(".pdf"):
        return jsonify(error="PDF receipt required"), 400

    content = receipt.read()

    if not content.startswith(b"%PDF-"):
        return jsonify(error="Invalid PDF file"), 400

    order_id = secrets.token_hex(5)
    total = amount * RATE

    orders[order_id] = {
        "user_id": int(user_id),
        "amount": amount,
        "total": total,
        "status": "pending"
    }

    caption = (
        f"🧾 НОВЫЙ ЗАКАЗ\n\n"
        f"Заказ: {order_id}\n"
        f"User ID: {user_id}\n"
        f"Username: @{username or 'не указан'}\n"
        f"Stars: {amount}\n"
        f"К оплате: {total:.2f} ₸\n"
        f"Статус: Ожидает проверки"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(
            "✅ Подтвердить",
            callback_data=f"approve:{order_id}"
        ),
        types.InlineKeyboardButton(
            "❌ Отклонить",
            callback_data=f"reject:{order_id}"
        )
    )

    try:
        bot.send_document(
            ADMIN_ID,
            document=io.BytesIO(content),
            visible_file_name="receipt.pdf",
            caption=caption,
            reply_markup=keyboard
        )
        bot.send_message(
            int(user_id),
            f"✅ Заказ {order_id} принят на проверку.\n"
            f"Количество: {amount} Stars\n"
            f"Сумма: {total:.2f} ₸"
        )
    except Exception:
        orders.pop(order_id, None)
        return jsonify(error="Could not send order to admin"), 500

    return jsonify(ok=True, order_id=order_id)

@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("approve:", "reject:"))
)
def process_order(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    action, order_id = call.data.split(":", 1)
    order = orders.get(order_id)

    if not order:
        bot.answer_callback_query(call.id, "Заказ не найден")
        return

    if order["status"] != "pending":
        bot.answer_callback_query(call.id, "Заказ уже обработан")
        return

    user_id = order["user_id"]

    if action == "approve":
        order["status"] = "approved"
        bot.send_message(
            user_id,
            f"✅ Заказ {order_id} подтверждён администратором.\n"
            f"Количество: {order['amount']} Stars\n"
            "Заказ принят в обработку."
        )
        bot.answer_callback_query(call.id, "Заказ подтверждён")
    else:
        order["status"] = "rejected"
        bot.send_message(
            user_id,
            f"❌ Заказ {order_id} отклонён.\n"
            "Если оплата выполнена, свяжитесь с поддержкой."
        )
        bot.answer_callback_query(call.id, "Заказ отклонён")

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
