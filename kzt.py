import asyncio
import logging
import os
import sqlite3
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
)
from aiocryptopay import AioCryptoPay, Networks

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN", "")
TON_WALLET = os.getenv("TON_WALLET", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CHAT_LINK = os.getenv("CHAT_LINK", "")
DB_PATH = os.getenv("DB_PATH", "/data/railtry.db")

BET_MIN = 0.1
BET_MAX = 10000
WITHDRAW_MIN = 1
REF_PERCENT = 0.10
HOUSE_EDGE = 0.05
TON_USD = 5.0
STAR_USD = 0.013

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

crypto = None
try:
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)
    print("✅ CryptoPay OK")
except Exception as e:
    print(f"❌ CryptoPay: {e}")

awaiting = {}


# ==================== DB ====================
def db_init():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        try: os.makedirs(db_dir, exist_ok=True)
        except: pass
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
        ref INTEGER, refs INTEGER DEFAULT 0, total_bets REAL DEFAULT 0,
        games_played INTEGER DEFAULT 0, total_won REAL DEFAULT 0,
        total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0,
        registered TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS multichecks (
        code TEXT PRIMARY KEY, total REAL, slots INTEGER, per_user REAL,
        min_turnover REAL DEFAULT 0, claimed INTEGER DEFAULT 0,
        activated_by TEXT DEFAULT '', creator INTEGER, active INTEGER DEFAULT 1,
        created TEXT)""")
    conn.commit()
    c.execute("SELECT COUNT(*) FROM users")
    uc = c.fetchone()[0]
    conn.close()
    print(f"📁 DB: {DB_PATH} | 👥 {uc}")


def db_get(uid, username=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    if not row:
        name = username or f"Player{uid%10000}"
        c.execute("INSERT INTO users(uid,username,registered) VALUES(?,?,?)",
                  (uid, name, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        c.execute("SELECT * FROM users WHERE uid=?", (uid,))
        row = c.fetchone()
    elif username:
        c.execute("UPDATE users SET username=? WHERE uid=?", (username, uid))
        conn.commit()
    conn.close()
    return {"uid": row[0], "username": row[1], "balance": row[2], "ref": row[3],
            "refs": row[4], "total_bets": row[5], "games_played": row[6],
            "total_won": row[7], "total_deposit": row[8], "total_withdraw": row[9],
            "registered": row[10]} if row else None


def db_upd(uid, **kw):
    if not kw: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    f = ", ".join(f"{k}=?" for k in kw)
    c.execute(f"UPDATE users SET {f} WHERE uid=?", list(kw.values()) + [uid])
    conn.commit()
    conn.close()


def fmt(b): return f"{b:.2f}"
def uname(u): return f"@{u.username}" if u.username else u.first_name


# ==================== KEYBOARDS ====================
def reply_kb(uid):
    kb = [
        [KeyboardButton(text="🎮  Играть"), KeyboardButton(text="🏆  Топ")],
        [KeyboardButton(text="💰  Баланс"), KeyboardButton(text="👤  Профиль")],
    ]
    if uid == ADMIN_ID:
        kb.append([KeyboardButton(text="👑  Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def kb_games():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲  Кости", callback_data="dice"),
         InlineKeyboardButton(text="🎯  Дартс", callback_data="darts")],
        [InlineKeyboardButton(text="⚽  Футбол", callback_data="football"),
         InlineKeyboardButton(text="🏀  Баскетбол", callback_data="basketball")],
        [InlineKeyboardButton(text="🎳  Боулинг", callback_data="bowling"),
         InlineKeyboardButton(text="🎰  777", callback_data="slot")],
    ])


def kb_dice():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️  Больше (4-6)   ·   x2", callback_data="dice_more")],
        [InlineKeyboardButton(text="⬇️  Меньше (1-3)   ·   x2", callback_data="dice_less")],
        [InlineKeyboardButton(text="➗  Чётное (2,4,6)   ·   x2", callback_data="dice_even")],
        [InlineKeyboardButton(text="➖  Нечётное (1,3,5)   ·   x2", callback_data="dice_odd")],
        [InlineKeyboardButton(text="🎯  Угадать число   ·   x5", callback_data="dice_exact")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_dice_num():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣", callback_data="dice_n_1"),
         InlineKeyboardButton(text="2️⃣", callback_data="dice_n_2"),
         InlineKeyboardButton(text="3️⃣", callback_data="dice_n_3")],
        [InlineKeyboardButton(text="4️⃣", callback_data="dice_n_4"),
         InlineKeyboardButton(text="5️⃣", callback_data="dice_n_5"),
         InlineKeyboardButton(text="6️⃣", callback_data="dice_n_6")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="dice")],
    ])


def kb_darts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴  Красный сектор   ·   x2.5", callback_data="darts_red")],
        [InlineKeyboardButton(text="⚪  Белый сектор   ·   x2.5", callback_data="darts_white")],
        [InlineKeyboardButton(text="🎯  Центр   ·   x5", callback_data="darts_center")],
        [InlineKeyboardButton(text="↩️  Отскок   ·   x5", callback_data="darts_bounce")],
        [InlineKeyboardButton(text="✨  Сектор Дубль   ·   x5", callback_data="darts_double")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_football():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽  Чистый гол   ·   x1.7", callback_data="fb_goal")],
        [InlineKeyboardButton(text="❌  Промах   ·   x2", callback_data="fb_miss")],
        [InlineKeyboardButton(text="🥅  Удар об штангу   ·   x3", callback_data="fb_post")],
        [InlineKeyboardButton(text="✨  Гол с помощью штанг   ·   x5", callback_data="fb_postgoal")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_basketball():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏀  Чистый гол   ·   x2.5", callback_data="bb_goal")],
        [InlineKeyboardButton(text="❌  Промах   ·   x1.77", callback_data="bb_miss")],
        [InlineKeyboardButton(text="🌀  Прокрут   ·   x3", callback_data="bb_spin")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_bowling():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌  Промах   ·   x5", callback_data="bl_miss")],
        [InlineKeyboardButton(text="🎳  Страйк   ·   x5", callback_data="bl_strike")],
        [InlineKeyboardButton(text="🎯  Угадать сбито   ·   x8", callback_data="bl_exact")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_bowling_num():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="bl_n_1"),
         InlineKeyboardButton(text="2", callback_data="bl_n_2"),
         InlineKeyboardButton(text="3", callback_data="bl_n_3")],
        [InlineKeyboardButton(text="4", callback_data="bl_n_4"),
         InlineKeyboardButton(text="5", callback_data="bl_n_5"),
         InlineKeyboardButton(text="6", callback_data="bl_n_6")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="bowling")],
    ])


def kb_slot():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰  777 Джекпот   ·   x30", callback_data="slot_777")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_games")],
    ])


def kb_top():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰  По балансу", callback_data="top_bal"),
         InlineKeyboardButton(text="🎮  По играм", callback_data="top_g")],
        [InlineKeyboardButton(text="👥  По рефералам", callback_data="top_r")],
    ])


def kb_balance():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳  Пополнить", callback_data="deposit_menu"),
         InlineKeyboardButton(text="📤  Вывести", callback_data="withdraw")],
    ])


def kb_profile():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥  Реферальная ссылка", callback_data="ref_link")],
        [InlineKeyboardButton(text="📊  Моя статистика", callback_data="my_stats")],
    ])


def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊  Статистика", callback_data="ad_stats"),
         InlineKeyboardButton(text="👥  Игроки", callback_data="ad_users")],
        [InlineKeyboardButton(text="🎫  МультиЧек", callback_data="ad_multicheck")],
        [InlineKeyboardButton(text="📋  Активные чеки", callback_data="ad_checks")],
    ])


def kb_deposit_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎  CryptoBot (USDT)", callback_data="dep_crypto")],
        [InlineKeyboardButton(text="💠  TonKeeper (TON)", callback_data="dep_ton")],
        [InlineKeyboardButton(text="⭐  Telegram Stars", callback_data="dep_stars")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="menu_balance")],
    ])


def kb_crypto_amounts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1$", callback_data="cp_1"),
         InlineKeyboardButton(text="5$", callback_data="cp_5"),
         InlineKeyboardButton(text="10$", callback_data="cp_10")],
        [InlineKeyboardButton(text="25$", callback_data="cp_25"),
         InlineKeyboardButton(text="50$", callback_data="cp_50"),
         InlineKeyboardButton(text="100$", callback_data="cp_100")],
        [InlineKeyboardButton(text="✏️  Своя сумма", callback_data="cp_custom")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="deposit_menu")],
    ])


def kb_ton_amounts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 TON", callback_data="ton_1"),
         InlineKeyboardButton(text="2 TON", callback_data="ton_2"),
         InlineKeyboardButton(text="5 TON", callback_data="ton_5")],
        [InlineKeyboardButton(text="10 TON", callback_data="ton_10"),
         InlineKeyboardButton(text="✏️  Своя сумма", callback_data="ton_custom")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="deposit_menu")],
    ])


def kb_stars_amounts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 50 Stars", callback_data="st_50"),
         InlineKeyboardButton(text="⭐ 100 Stars", callback_data="st_100")],
        [InlineKeyboardButton(text="⭐ 250 Stars", callback_data="st_250"),
         InlineKeyboardButton(text="⭐ 500 Stars", callback_data="st_500")],
        [InlineKeyboardButton(text="✏️  Своя сумма", callback_data="st_custom")],
        [InlineKeyboardButton(text="⬅️  Назад", callback_data="deposit_menu")],
    ])


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    uid = m.from_user.id
    name = uname(m.from_user)
    u = db_get(uid, name)
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref") and u["ref"] is None:
        try:
            rid = int(args[1].replace("ref", ""))
            if rid != uid:
                db_upd(uid, ref=rid)
                ru = db_get(rid)
                db_upd(rid, refs=ru["refs"] + 1)
                try: await bot.send_message(rid, "🎉 Новый реферал!")
                except: pass
        except: pass
    await m.answer(
        f"🚀  <b>RAILTRY</b>\n\n"
        f"👋  Привет, <b>{name}</b>!\n\n"
        f"💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n"
        f"Выбери действие ниже 👇",
        reply_markup=reply_kb(uid), parse_mode="HTML"
    )


# ==================== REPLY BUTTONS ====================
@dp.message(F.text.contains("Играть"))
async def btn_play(m: types.Message):
    await m.answer(
        "🎮  <b>Выбери игру</b>\n\n"
        "🎲  <b>Кости</b> — угадай бросок\n"
        "🎯  <b>Дартс</b> — попади в цель\n"
        "⚽  <b>Футбол</b> — забей гол\n"
        "🏀  <b>Баскетбол</b> — попади в кольцо\n"
        "🎳  <b>Боулинг</b> — сбей кегли\n"
        "🎰  <b>777</b> — поймай джекпот",
        reply_markup=kb_games(), parse_mode="HTML"
    )


@dp.message(F.text.contains("Топ"))
async def btn_top(m: types.Message):
    await m.answer("🏆  <b>Топы игроков</b>", reply_markup=kb_top(), parse_mode="HTML")


@dp.message(F.text.contains("Баланс"))
async def btn_bal(m: types.Message):
    uid = m.from_user.id
    u = db_get(uid, uname(m.from_user))
    await m.answer(
        f"💰  <b>Ваш баланс</b>\n\n"
        f"💵  Доступно: <b>{fmt(u['balance'])}$</b>\n\n"
        f"Что хотите сделать?",
        reply_markup=kb_balance(), parse_mode="HTML"
    )


@dp.message(F.text.contains("Профиль"))
async def btn_prof(m: types.Message):
    uid = m.from_user.id
    u = db_get(uid, uname(m.from_user))
    await m.answer(
        f"👤  <b>Ваш профиль</b>\n\n"
        f"📛  Ник: <b>{u['username']}</b>\n"
        f"💰  Баланс: <b>{fmt(u['balance'])}$</b>\n"
        f"👥  Рефералов: <b>{u['refs']}</b>\n"
        f"💸  Оборот: <b>{fmt(u['total_bets'])}$</b>",
        reply_markup=kb_profile(), parse_mode="HTML"
    )


@dp.message(F.text.contains("Админ-панель"))
async def btn_admin(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    await m.answer("👑  <b>Админ-панель</b>", reply_markup=kb_admin(), parse_mode="HTML")


# ==================== MENU CALLBACKS ====================
@dp.callback_query(F.data == "menu_games")
async def cb_menu_games(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🎮  <b>Выбери игру</b>\n\n"
        "🎲  <b>Кости</b> — угадай бросок\n"
        "🎯  <b>Дартс</b> — попади в цель\n"
        "⚽  <b>Футбол</b> — забей гол\n"
        "🏀  <b>Баскетбол</b> — попади в кольцо\n"
        "🎳  <b>Боулинг</b> — сбей кегли\n"
        "🎰  <b>777</b> — поймай джекпот",
        reply_markup=kb_games(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "menu_balance")
async def cb_menu_bal(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid)
    await cb.message.edit_text(
        f"💰  <b>Ваш баланс</b>\n\n💵  Доступно: <b>{fmt(u['balance'])}$</b>",
        reply_markup=kb_balance(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "my_stats")
async def cb_my_stats(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid)
    await cb.message.edit_text(
        f"📊  <b>Моя статистика</b>\n\n"
        f"🎮  Игр: <b>{u['games_played']}</b>\n"
        f"💵  Ставок: <b>{fmt(u['total_bets'])}$</b>\n"
        f"🏆  Выиграно: <b>{fmt(u['total_won'])}$</b>\n"
        f"💳  Пополнений: <b>{fmt(u['total_deposit'])}$</b>\n"
        f"📤  Выведено: <b>{fmt(u['total_withdraw'])}$</b>\n"
        f"👥  Рефералов: <b>{u['refs']}</b>",
        reply_markup=kb_profile(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "ref_link")
async def cb_ref_link(cb: types.CallbackQuery):
    uid = cb.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{uid}"
    u = db_get(uid)
    await cb.message.edit_text(
        f"👥  <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей — получай <b>10%</b> с их пополнений!\n\n"
        f"🔗  Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥  Приглашено: <b>{u['refs']}</b>",
        reply_markup=kb_profile(), parse_mode="HTML"
    )
    await cb.answer()


# ==================== ОЙЫН CALLBACKS ====================
@dp.callback_query(F.data == "dice")
async def cb_dice(cb: types.CallbackQuery):
    await cb.message.edit_text("🎲  <b>КОСТИ</b>\n\nУгадай результат броска!",
                                reply_markup=kb_dice(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("dice_"))
async def cb_dice_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    data = cb.data.replace("dice_", "")
    if data == "exact":
        await cb.message.edit_text("🎯  <b>Угадай число</b>\n\nКакое число выпадет?",
                                    reply_markup=kb_dice_num(), parse_mode="HTML")
        await cb.answer(); return
    if data.startswith("n_"):
        n = int(data.replace("n_", ""))
        awaiting[uid] = {"game": "dice", "bet": f"n_{n}"}
    else:
        awaiting[uid] = {"game": "dice", "bet": data}
    u = db_get(uid)
    await cb.message.answer(f"🎲  <b>Кости</b>\n\n💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:", parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "darts")
async def cb_darts(cb: types.CallbackQuery):
    await cb.message.edit_text("🎯  <b>ДАРТС</b>\n\nКуда попадёт дротик?",
                                reply_markup=kb_darts(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("darts_"))
async def cb_darts_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    bt = cb.data.replace("darts_", "")
    awaiting[uid] = {"game": "darts", "bet": bt}
    u = db_get(uid)
    await cb.message.answer(f"🎯  <b>Дартс</b>\n\n💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:", parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "football")
async def cb_football(cb: types.CallbackQuery):
    await cb.message.edit_text("⚽  <b>ФУТБОЛ</b>\n\nЧто произойдёт?",
                                reply_markup=kb_football(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("fb_"))
async def cb_fb_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    bt = cb.data.replace("fb_", "")
    awaiting[uid] = {"game": "football", "bet": bt}
    u = db_get(uid)
    await cb.message.answer(f"⚽  <b>Футбол</b>\n\n💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:", parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "basketball")
async def cb_basketball(cb: types.CallbackQuery):
    await cb.message.edit_text("🏀  <b>БАСКЕТБОЛ</b>\n\nЧто произойдёт?",
                                reply_markup=kb_basketball(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("bb_"))
async def cb_bb_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    bt = cb.data.replace("bb_", "")
    awaiting[uid] = {"game": "basketball", "bet": bt}
    u = db_get(uid)
    await cb.message.answer(f"🏀  <b>Баскетбол</b>\n\n💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:", parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "bowling")
async def cb_bowling(cb: types.CallbackQuery):
    await cb.message.edit_text("🎳  <b>БОУЛИНГ</b>\n\nВыбери тип ставки:",
                                reply_markup=kb_bowling(), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("bl_"))
async def cb_bl_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    data = cb.data.replace("bl_", "")
    if data == "exact":
        await cb.message.edit_text("🎯  <b>Угадай сбито</b> (x8)\n\nСколько кеглей?",
                                    reply_markup=kb_bowling_num(), parse_mode="HTML")
        await cb.
        # ==================== ОЙЫН ЛОГИКАСЫ ====================
@dp.message(F.text.regexp(r"^\d+(\.\d+)?$"))
async def msg_num(m: types.Message):
    uid = m.from_user.id
    name = uname(m.from_user)
    u = db_get(uid, name)
    val = float(m.text)

    # === Пополнение: своя сумма ===
    if uid in awaiting and awaiting[uid].get("dep_custom"):
        method = awaiting[uid].get("method")
        awaiting.pop(uid)
        if val < 1 or val > 10000:
            await m.answer("❌  Сумма 1-10000$"); return
        if method == "crypto":
            await do_crypto_deposit(m, uid, val)
        return

    # === TON: своя сумма ===
    if uid in awaiting and awaiting[uid].get("ton_custom"):
        awaiting.pop(uid)
        if val < 0.1 or val > 1000:
            await m.answer("❌  TON 0.1-1000"); return
        await do_ton_deposit(m, uid, val)
        return

    # === Stars: своя сумма ===
    if uid in awaiting and awaiting[uid].get("stars_custom"):
        awaiting.pop(uid)
        stars = int(val)
        if stars < 50 or stars > 10000:
            await m.answer("❌  Stars 50-10000"); return
        await do_stars_invoice(m, uid, stars)
        return

    # === Вывод ===
    if uid in awaiting and awaiting[uid].get("withdraw"):
        awaiting.pop(uid)
        if val < WITHDRAW_MIN: await m.answer(f"❌  Мин: {WITHDRAW_MIN}$"); return
        if val > u["balance"]: await m.answer("❌  Недостаточно"); return
        await do_withdraw(m, uid, val); return

    # === Игра ===
    if uid not in awaiting or "game" not in awaiting[uid]:
        return

    t = awaiting[uid]
    g = t["game"]
    if val < BET_MIN: await m.answer(f"❌  Мин: {BET_MIN}$"); return
    if val > BET_MAX: await m.answer(f"❌  Макс: {BET_MAX}$"); return
    if val > u["balance"]: await m.answer(f"❌  Недостаточно. Баланс: {fmt(u['balance'])}$"); return

    new_bal = round(u["balance"] - val, 2)
    db_upd(uid, balance=new_bal)
    awaiting.pop(uid)

    # ============ КОСТИ ============
    if g == "dice":
        bt = t["bet"]
        dm = await m.answer_dice(emoji="🎲")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        mult = 2
        if bt == "more": 
            win = r >= 4
            txt = f"🎲  Выпало <b>{r}</b> → " + ("Больше 3 ✅" if win else "Не больше 3 ❌")
        elif bt == "less":
            win = r <= 3
            txt = f"🎲  Выпало <b>{r}</b> → " + ("Меньше 4 ✅" if win else "Не меньше 4 ❌")
        elif bt == "even":
            win = r in [2, 4, 6]
            txt = f"🎲  Выпало <b>{r}</b> → " + ("Чётное ✅" if win else "Не чётное ❌")
        elif bt == "odd":
            win = r in [1, 3, 5]
            txt = f"🎲  Выпало <b>{r}</b> → " + ("Нечётное ✅" if win else "Не нечётное ❌")
        elif bt.startswith("n_"):
            n = int(bt.replace("n_", ""))
            mult = 5
            win = (r == n)
            txt = f"🎲  Выпало <b>{r}</b> → " + (f"Угадал {n} ✅" if win else f"Не угадал ❌")
        await end_game(m, uid, val, win, mult, txt, "dice")
        return

    # ============ ДАРТС ============
    if g == "darts":
        bt = t["bet"]
        dm = await m.answer_dice(emoji="🎯")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        mult = 2.5
        # 1=промах, 2=🔴красный, 3=⚪белый, 4=🎯дубль, 5=↩️отскок, 6=🎯центр
        if bt == "red":
            win = (r == 2)
            txt = f"🎯  Выпало <b>{r}</b> → " + ("🔴 Красный ✅" if win else "Не красный ❌")
        elif bt == "white":
            win = (r == 3)
            txt = f"🎯  Выпало <b>{r}</b> → " + ("⚪ Белый ✅" if win else "Не белый ❌")
        elif bt == "center":
            win = (r == 6); mult = 5
            txt = f"🎯  Выпало <b>{r}</b> → " + ("🎯 Центр ✅" if win else "Не центр ❌")
        elif bt == "bounce":
            win = (r == 5); mult = 5
            txt = f"🎯  Выпало <b>{r}</b> → " + ("↩️ Отскок ✅" if win else "Не отскок ❌")
        elif bt == "double":
            win = (r == 4); mult = 5
            txt = f"🎯  Выпало <b>{r}</b> → " + ("✨ Сектор Дубль ✅" if win else "Не дубль ❌")
        await end_game(m, uid, val, win, mult, txt, "darts")
        return

    # ============ ФУТБОЛ ============
    if g == "football":
        bt = t["bet"]
        dm = await m.answer_dice(emoji="⚽")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        mult = 2
        # 1=штанга, 2=гол со штанг, 3=промах, 4-5=чистый гол
        if bt == "goal":
            win = (r >= 4); mult = 1.7
            txt = f"⚽  Выпало <b>{r}</b> → " + ("Чистый гол ✅" if win else "Не гол ❌")
        elif bt == "miss":
            win = (r == 3); mult = 2
            txt = f"⚽  Выпало <b>{r}</b> → " + ("Промах ✅" if win else "Не промах ❌")
        elif bt == "post":
            win = (r == 1); mult = 3
            txt = f"⚽  Выпало <b>{r}</b> → " + ("🥅 Удар об штангу ✅" if win else "Не штанга ❌")
        elif bt == "postgoal":
            win = (r == 2); mult = 5
            txt = f"⚽  Выпало <b>{r}</b> → " + ("✨ Гол с помощью штанг ✅" if win else "Не гол со штанг ❌")
        await end_game(m, uid, val, win, mult, txt, "football")
        return

    # ============ БАСКЕТБОЛ ============
    if g == "basketball":
        bt = t["bet"]
        dm = await m.answer_dice(emoji="🏀")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        mult = 2
        # 1=промах, 2=прокрут, 3=промах, 4-5=чистый гол
        if bt == "goal":
            win = (r >= 4); mult = 2.5
            txt = f"🏀  Выпало <b>{r}</b> → " + ("Чистый гол ✅" if win else "Не гол ❌")
        elif bt == "miss":
            win = r in [1, 3]; mult = 1.77
            txt = f"🏀  Выпало <b>{r}</b> → " + ("Промах ✅" if win else "Не промах ❌")
        elif bt == "spin":
            win = (r == 2); mult = 3
            txt = f"🏀  Выпало <b>{r}</b> → " + ("🌀 Прокрут ✅" if win else "Не прокрут ❌")
        await end_game(m, uid, val, win, mult, txt, "basketball")
        return

    # ============ БОУЛИНГ ============
    if g == "bowling":
        bt = t["bet"]
        dm = await m.answer_dice(emoji="🎳")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        mult = 5
        if bt == "miss":
            win = (r == 1)
            txt = f"🎳  Выпало <b>{r}</b>/6 → " + ("Промах ✅" if win else "Не промах ❌")
        elif bt == "strike":
            win = (r == 6)
            txt = f"🎳  Выпало <b>{r}</b>/6 → " + ("Страйк ✅" if win else "Не страйк ❌")
        elif bt.startswith("n_"):
            n = int(bt.replace("n_", ""))
            mult = 8
            win = (r == n)
            txt = f"🎳  Выпало <b>{r}</b>/6 → " + (f"Угадал {n} ✅" if win else f"Не угадал ❌")
        await end_game(m, uid, val, win, mult, txt, "bowling")
        return

    # ============ 777 ============
    if g == "slot":
        dm = await m.answer_dice(emoji="🎰")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = (r == 64)
        mult = 30
        txt = f"🎰  Выпало <b>{r}</b> → " + ("🎰 777 ДЖЕКПОТ ✅" if win else "Не 777 ❌")
        await end_game(m, uid, val, win, mult, txt, "slot")
        return


async def end_game(msg, uid, bet, win, mult, text_res, game_code):
    u = db_get(uid)
    if win:
        wf = round(bet * mult, 2)
        comm = round(wf * HOUSE_EDGE, 2)
        profit = round(wf - comm, 2)
        nb = round(u["balance"] + profit, 2)
        db_upd(uid, balance=nb, total_bets=round(u["total_bets"] + bet, 2),
               games_played=u["games_played"] + 1, total_won=round(u["total_won"] + profit, 2))
        text = (f"🎉  <b>ПОБЕДА!</b>\n\n📊  {text_res}\n\n"
                f"💵  Ставка: {fmt(bet)}$\n🎯  x{mult}\n"
                f"➕  Выигрыш: <b>+{fmt(profit)}$</b>\n💰  Баланс: <b>{fmt(nb)}$</b>")
    else:
        db_upd(uid, total_bets=round(u["total_bets"] + bet, 2), games_played=u["games_played"] + 1)
        text = (f"😢  <b>ПРОИГРЫШ</b>\n\n📊  {text_res}\n\n"
                f"💸  Потеряно: <b>-{fmt(bet)}$</b>\n💰  Баланс: <b>{fmt(u['balance'])}$</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄  Снова", callback_data=game_code),
         InlineKeyboardButton(text="🏠  В меню", callback_data="menu_games")],
    ])
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


# ==================== ПОПОЛНЕНИЕ ====================
@dp.callback_query(F.data == "deposit_menu")
async def cb_dep_menu(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "💳  <b>Пополнение</b>\n\n"
        "Выбери способ оплаты:\n\n"
        "💎  <b>CryptoBot</b> — USDT (быстро)\n"
        "💠  <b>TonKeeper</b> — TON (низкая комиссия)\n"
        "⭐  <b>Telegram Stars</b> — Stars (внутри Telegram)",
        reply_markup=kb_deposit_menu(), parse_mode="HTML"
    )
    await cb.answer()


# === CRYPTO ===
@dp.callback_query(F.data == "dep_crypto")
async def cb_dep_crypto(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "💎  <b>CryptoBot — USDT</b>\n\nВыбери сумму:",
        reply_markup=kb_crypto_amounts(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("cp_"))
async def cb_cp_amt(cb: types.CallbackQuery):
    d = cb.data.replace("cp_", "")
    uid = cb.from_user.id
    if d == "custom":
        awaiting[uid] = {"dep_custom": True, "method": "crypto"}
        await cb.message.answer("✏️  Введи сумму (1-10000$):")
        await cb.answer(); return
    await do_crypto_deposit(cb.message, uid, float(d))
    await cb.answer()


async def do_crypto_deposit(msg, uid, amount):
    if not crypto:
        await msg.answer("❌  CryptoBot недоступен"); return
    try:
        inv = await crypto.create_invoice(asset="USDT", amount=amount,
            description=f"RailTry #{uid}", payload=f"dep_{uid}_{amount}", expires_in=1800)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳  Оплатить", url=inv.bot_invoice_url)],
            [InlineKeyboardButton(text="✅  Проверить", callback_data=f"chk_{inv.invoice_id}_{amount}")],
        ])
        await msg.answer(
            f"💎  <b>Счёт на {amount}$</b>\n\n"
            f"Оплати по кнопке ниже 👇\n\n"
            f"✅  После оплаты нажми «Проверить»",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(f"❌  Ошибка: <code>{e}</code>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("chk_"))
async def cb_chk(cb: types.CallbackQuery):
    p = cb.data.split("_")
    iid, amount, uid = int(p[1]), float(p[2]), cb.from_user.id
    try:
        inv = await crypto.get_invoices(invoice_ids=iid)
        if isinstance(inv, list): inv = inv[0] if inv else None
        if inv and inv.status == "paid":
            u = db_get(uid)
            nb = round(u["balance"] + amount, 2)
            nd = round(u["total_deposit"] + amount, 2)
            db_upd(uid, balance=nb, total_deposit=nd)
            await cb.message.answer(
                f"✅  <b>Оплата подтверждена!</b>\n\n"
                f"💵  +{amount}$\n💰  Баланс: <b>{fmt(nb)}$</b>",
                parse_mode="HTML"
            )
            if u["ref"]:
                bonus = round(amount * REF_PERCENT, 2)
                ru = db_get(u["ref"])
                db_upd(u["ref"], balance=round(ru["balance"] + bonus, 2))
                try:
                    await bot.send_message(u["ref"], f"💸  +{bonus}$ реф. бонус")
                except: pass
        else:
            await cb.message.answer("⏳  Ещё не оплачено")
    except Exception as e:
        await cb.message.answer(f"❌  Ошибка: {e}")
    await cb.answer()


# === TON ===
@dp.callback_query(F.data == "dep_ton")
async def cb_dep_ton(cb: types.CallbackQuery):
    await cb.message.edit_text(
        f"💠  <b>TonKeeper — TON</b>\n\n"
        f"Курс: 1 TON ≈ <b>{TON_USD}$</b>\n\n"
        f"Выбери сумму:",
        reply_markup=kb_ton_amounts(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("ton_"))
async def cb_ton_amt(cb: types.CallbackQuery):
    d = cb.data.replace("ton_", "")
    uid = cb.from_user.id
    if d == "custom":
        awaiting[uid] = {"ton_custom": True}
        await cb.message.answer("✏️  Введи сумму в TON (0.1-1000):")
        await cb.answer(); return
    await do_ton_deposit(cb.message, uid, float(d))
    await cb.answer()


async def do_ton_deposit(msg, uid, ton_amount):
    if not TON_WALLET:
        await msg.answer("❌  TON_WALLET не настроен в Railway Variables")
        return
    usd_amount = round(ton_amount * TON_USD, 2)
    await msg.answer(
        f"💠  <b>Оплата TON</b>\n\n"
        f"💵  Сумма: <b>{ton_amount} TON</b>\n"
        f"💰  Получишь: <b>{usd_amount}$</b>\n"
        f"📊  Курс: 1 TON = {TON_USD}$\n\n"
        f"📮  Отправь TON на адрес:\n"
        f"<code>{TON_WALLET}</code>\n\n"
        f"⚠️  <b>Комментарий к переводу:</b>\n"
        f"<code>RT{uid}</code>\n\n"
        f"❗ Без комментария платёж не будет зачислен!\n\n"
        f"✅  После отправки нажми «Проверить»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅  Я оплатил", callback_data=f"toncheck_{uid}_{ton_amount}")],
            [InlineKeyboardButton(text="⬅️  Назад", callback_data="deposit_menu")],
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("toncheck_"))
async def cb_toncheck(cb: types.CallbackQuery):
    p = cb.data.split("_")
    uid, ton_amount = int(p[1]), float(p[2])
    await cb.message.answer(
        f"⏳  <b>Проверка платежа...</b>\n\n"
        f"Обычно занимает 1-5 минут.\n"
        f"Админ проверит вручную.",
        parse_mode="HTML"
    )
    usd_amount = round(ton_amount * TON_USD, 2)
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💠  <b>TON платёж</b>\n\n"
            f"👤  User: <code>{uid}</code>\n"
            f"💵  {ton_amount} TON ({usd_amount}$)\n"
            f"🔍  Проверь кошелёк: <code>{TON_WALLET}</code>\n"
            f"💬  Комментарий: <code>RT{uid}</code>\n\n"
            f"Зачислить: <code>/addton {uid} {ton_amount}</code>",
            parse_mode="HTML"
        )
    except: pass
    await cb.answer()


@dp.message(Command("addton"))
async def cmd_addton(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    args = m.text.split()
    if len(args) < 3:
        await m.answer("📋  /addton <uid> <ton_amount>"); return
    try:
        uid = int(args[1])
        ton_amount = float(args[2])
    except:
        await m.answer("❌  Неверный формат"); return
    usd = round(ton_amount * TON_USD, 2)
    u = db_get(uid)
    nb = round(u["balance"] + usd, 2)
    nd = round(u["total_deposit"] + usd, 2)
    db_upd(uid, balance=nb, total_deposit=nd)
    await m.answer(
        f"✅  <b>Зачислено</b>\n\n"
        f"👤  User: <code>{uid}</code>\n"
        f"💠  {ton_amount} TON = {usd}$\n"
        f"💰  Новый баланс: {fmt(nb)}$",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(uid,
            f"✅  <b>TON пополнение!</b>\n\n"
            f"💠  {ton_amount} TON\n"
            f"💰  +{usd}$\n"
            f"💵  Баланс: {fmt(nb)}$",
            parse_mode="HTML")
    except: pass


# === STARS ===
@dp.callback_query(F.data == "dep_stars")
async def cb_dep_stars(cb: types.CallbackQuery):
    await cb.message.edit_text(
        f"⭐  <b>Telegram Stars</b>\n\n"
        f"Курс: 1 Star ≈ {STAR_USD}$\n\n"
        f"Выбери сумму:",
        reply_markup=kb_stars_amounts(), parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("st_"))
async def cb_st_amt(cb: types.CallbackQuery):
    d = cb.data.replace("st_", "")
    uid = cb.from_user.id
    if d == "custom":
        awaiting[uid] = {"stars_custom": True}
        await cb.message.answer("✏️  Введи кол-во Stars (50-10000):")
        await cb.answer(); return
    await do_stars_invoice(cb.message, uid, int(d))
    await cb.answer()


async def do_stars_invoice(msg, uid, stars):
    try:
        usd = round(stars * STAR_USD, 2)
        await bot.send_invoice(
            chat_id=uid,
            title="⭐ Пополнение баланса",
            description=f"+{usd}$ на баланс RailTry",
            payload=f"stars_{uid}_{stars}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="XTR", amount=stars)],
        )
    except Exception as e:
        await msg.answer(f"❌  Ошибка: <code>{e}</code>", parse_mode="HTML")


@dp.pre_checkout_query()
async def pre_checkout(q: types.PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def on_stars_paid(m: types.Message):
    uid = m.from_user.id
    payload = m.successful_payment.invoice_payload
    stars = m.successful_payment.total_amount
    try:
        usd = round(stars * STAR_USD, 2)
        u = db_get(uid)
        nb = round(u["balance"] + usd, 2)
        nd = round(u["total_deposit"] + usd, 2)
        db_upd(uid, balance=nb, total_deposit=nd)
        await m.answer(
            f"✅  <b>Оплата Stars успешна!</b>\n\n"
            f"⭐  {stars} Stars\n"
            f"💰  +{usd}$\n"
            f"💵  Баланс: <b>{fmt(nb)}$</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await m.answer(f"❌  Ошибка начисления: {e}")


# ==================== ВЫВОД ====================
@dp.callback_query(F.data == "withdraw")
async def cb_wd(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid)
    if u["balance"] < WITHDRAW_MIN:
        await cb.answer(f"Мин: {WITHDRAW_MIN}$", show_alert=True); return
    awaiting[uid] = {"withdraw": True}
    await cb.message.answer(
        f"📤  <b>Вывод</b>\n\n"
        f"💰  Баланс: <b>{fmt(u['balance'])}$</b>\n\n"
        f"✏️  Введи сумму:",
        parse_mode="HTML"
    )
    await cb.answer()


async def do_withdraw(msg, uid, amount):
    u = db_get(uid)
    try:
        chk = await crypto.create_check(asset="USDT", amount=round(amount, 2), pin_to_user_id=uid)
        db_upd(uid, balance=round(u["balance"] - amount, 2),
               total_withdraw=round(u["total_withdraw"] + amount, 2))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵  Получить", url=chk.bot_check_url)]
        ])
        await msg.answer(
            f"✅  <b>Чек на {amount}$</b>\n\nАктивируй 👇",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(
            f"❌  <b>Вывод временно не работает</b>\n\n"
            f"Попробуйте позже.\n\n"
            f"<i>Код: {type(e).__name__}</i>",
            parse_mode="HTML"
        )


# ==================== ТОП ====================
@dp.callback_query(F.data.startswith("top_"))
async def cb_top_show(cb: types.CallbackQuery):
    t = cb.data.replace("top_", "")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    medals = ["🥇", "🥈", "🥉"]
    rows = []
    if t == "bal":
        c.execute("SELECT username, balance FROM users WHERE balance>0 ORDER BY balance DESC LIMIT 10")
        rows = c.fetchall()
        text = "💰  <b>ТОП ПО БАЛАНСУ</b>\n\n"
        for i, (n, b) in enumerate(rows, 1):
            m = medals[i - 1] if i <= 3 else f"<b>{i}.</b>"
            text += f"{m}  {n} — <b>{fmt(b)}$</b>\n"
    elif t == "g":
        c.execute("SELECT username, games_played FROM users WHERE games_played>0 ORDER BY games_played DESC LIMIT 10")
        rows = c.fetchall()
        text = "🎮  <b>ТОП ИГРОКОВ</b>\n\n"
        for i, (n, g) in enumerate(rows, 1):
            m = medals[i - 1] if i <= 3 else f"<b>{i}.</b>"
            text += f"{m}  {n} — <b>{g}</b> игр\n"
    else:
        c.execute("SELECT username, refs FROM users WHERE refs>0 ORDER BY refs DESC LIMIT 10")
        rows = c.fetchall()
        text = "👥  <b>ТОП РЕФЕРАЛОВ</b>\n\n"
        for i, (n, r) in enumerate(rows, 1):
            m = medals[i - 1] if i <= 3 else f"<b>{i}.</b>"
        
