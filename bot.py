import logging
import re
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from threading import Thread
from flask import Flask

# --- Flask Fake Server ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return 'Bot is running!'

def run_flask():
    app_flask.run(host='0.0.0.0', port=10000)

Thread(target=run_flask).start()

# --- Telegram Bot Logic ---
DATE, SELLER, DESCRIPTION, PRICE, UNIT, QUANTITY, NOTE, CONFIRM = range(8)

logging.basicConfig(level=logging.INFO)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/levkinbot-3f4c6dfcd2e8.json", scope)
client = gspread.authorize(creds)
sheet = client.open("LevkinsPayments").sheet1

BOT_TOKEN = os.environ["BOT_TOKEN"]

cancel_filter = MessageHandler(filters.Regex("^❌ Отмена$"), lambda u, c: cancel(u, c))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("➕ Новая запись"), KeyboardButton("❌ Отмена")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📆 Введите дату покупки (дд.мм.гггг):", reply_markup=reply_markup)
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_date = update.message.text.strip()
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", raw_date):
        await update.message.reply_text("❌ Введите дату в формате дд.мм.гггг (например, 02.06.2025)")
        return DATE
    try:
        datetime.strptime(raw_date, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text("❌ Такой даты не существует. Попробуйте снова.")
        return DATE
    context.user_data['date'] = raw_date
    await update.message.reply_text("👤 У кого покупка?")
    return SELLER

async def get_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['seller'] = update.message.text.strip()
    await update.message.reply_text("📦 Что купили?")
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text.strip()
    await update.message.reply_text("💰 Цена за единицу?")
    return PRICE

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_input = update.message.text.strip()
    try:
        price = float(price_input.replace(",", "."))
        context.user_data['price'] = price
    except ValueError:
        await update.message.reply_text("❌ Введите числовое значение (например: 12.5)")
        return PRICE
    await update.message.reply_text("📏 Единица измерения (например: кг, шт, л):")
    return UNIT

async def get_unit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['unit'] = update.message.text.strip()
    await update.message.reply_text("🔢 Количество?")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_input = update.message.text.strip()
    try:
        quantity = float(qty_input.replace(",", "."))
        context.user_data['quantity'] = quantity
    except ValueError:
        await update.message.reply_text("❌ Введите числовое значение (например: 4)")
        return QUANTITY
    await update.message.reply_text("📝 Примечание (или «–»):")
    return NOTE

async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['note'] = update.message.text.strip()
    price = context.user_data['price']
    quantity = context.user_data['quantity']
    total = round(price * quantity, 2)
    context.user_data['total'] = total

    summary = (
        f"📋 Проверьте данные:\n"
        f"Дата: {context.user_data['date']}\n"
        f"Продавец: {context.user_data['seller']}\n"
        f"Описание: {context.user_data['description']}\n"
        f"Ед. изм.: {context.user_data['unit']}\n"
        f"Цена за ед.: {context.user_data['price']}\n"
        f"Кол-во: {context.user_data['quantity']}\n"
        f"Сумма: {context.user_data['total']}\n"
        f"Примечание: {context.user_data['note']}\n\n"
        f"✅ Всё верно?"
    )
    buttons = [[
        InlineKeyboardButton("✅ Записать", callback_data="confirm"),
        InlineKeyboardButton("❌ Отменить", callback_data="cancel")
    ]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(buttons))
    return CONFIRM

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm":
        user = query.from_user
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            context.user_data['date'],
            context.user_data['seller'],
            context.user_data['description'],
            context.user_data['price'],
            context.user_data['unit'],
            context.user_data['quantity'],
            context.user_data['total'],
            context.user_data['note'],
            user.full_name,
            str(user.id),
            user.username or "-",
            user.phone_number if hasattr(user, 'phone_number') else "-",
            timestamp
        ]
        try:
            sheet.append_row(row)
        except Exception as e:
            logging.error(f"Ошибка при записи: {e}")
            await query.edit_message_text("❌ Ошибка при записи. Попробуйте позже.")
            return ConversationHandler.END
        buttons = [[
            InlineKeyboardButton("➕ Да", callback_data="again"),
            InlineKeyboardButton("❌ Нет", callback_data="exit")
        ]]
        await query.edit_message_text(
            "✅ Данные записаны в таблицу.\n\nХотите добавить ещё одну запись?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return CONFIRM
    elif query.data == "cancel":
        await query.edit_message_text("❌ Ввод отменён.")
        return ConversationHandler.END
    elif query.data == "again":
        await query.edit_message_text("📆 Введите дату новой покупки (дд.мм.гггг):")
        return DATE
    elif query.data == "exit":
        await query.edit_message_text("👋 Хорошо, ввод завершён.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Ввод отменён.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Новая запись$"), start)
        ],
        states={
            DATE: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            SELLER: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_seller)],
            DESCRIPTION: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            PRICE: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_price)],
            UNIT: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_unit)],
            QUANTITY: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            NOTE: [cancel_filter, MessageHandler(filters.TEXT & ~filters.COMMAND, get_note)],
            CONFIRM: [CallbackQueryHandler(handle_confirmation)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ Отмена$"), cancel)
        ]
    )
    app.add_handler(conv_handler)
    app.run_polling()
