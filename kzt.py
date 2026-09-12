import asyncio
import logging
import traceback
import os
import sqlite3
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiocryptopay import AioCryptoPay, Networks

# ==================== ТОКЕНДЕР ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHAT_LINK = os.getenv("CHAT_LINK", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")

# ==================== ШЕКТЕУЛЕР ====================
BET_MIN = 0.1
BET_MAX = 10000.0
WITHDRAW_MIN = 1.0
REF_PERCENT = 0.10

# ==================== ЛОГИКА ====================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)
    print("CryptoPay OK")
except Exception as e:
    print("CryptoPay ҚАТЕ:", e)
    crypto = None

# ==================== РОЗЫГРЫШТАР (жадыда) ====================
# {gid: {"amount": 10, "min_dep": 3, "participants": [uid1, uid2], "active": True, "chat_id": ..., "msg_id": ...}}
giveaways = {}
next_gid = [1]


# ==================== ДЕРЕКҚОР ====================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uid INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            ref INTEGER,
            refs INTEGER DEFAULT 0,
            total_bets REAL DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            total_won REAL DEFAULT 0,
            total_deposit REAL DEFAULT 0
        )
    """)
    # Ескі дерекқорларға total_deposit бағанын қосу
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN total_deposit REAL DEFAULT 0")
        conn.commit()
    except:
        pass
    conn.commit()
    conn.close()
    print(f"📁 Дерекқор: {DB_PATH}")


def db_get_user(uid, username=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    row = cursor.fetchone()

    if row is None:
        name = username or f"Player{uid % 10000}"
        cursor.execute("INSERT INTO users (uid, username) VALUES (?, ?)", (uid, name))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE uid = ?", (uid,))
        row = cursor.fetchone()
    elif username:
        cursor.execute("UPDATE users SET username = ? WHERE uid = ?", (username, uid))
        conn.commit()

    conn.close()
    if row:
        return {
            "uid": row[0], "username": row[1], "balance": row[2],
            "ref": row[3], "refs": row[4], "total_bets": row[5],
            "games_played": row[6], "total_won": row[7],
            "total_deposit": row[8] if len(row) > 8 else 0,
        }
    return None


def db_update_user(uid, **kwargs):
    if not kwargs:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [uid]
    cursor.execute(f"UPDATE users SET {fields} WHERE uid = ?", values)
    conn.commit()
    conn.close()


# ==================== ОЙЫНДАР ====================
GAMES = {
    "dice": {
        "emoji": "🎲", "name": "Кости", "choices": {
            "more3": {"name": "Больше (4-6)", "x": 2},
            "less3": {"name": "Меньше (1-3)", "x": 2},
            "even":  {"name": "Чётное (2,4,6)", "x": 2},
            "odd":   {"name": "Нечётное (1,3,5)", "x": 2},
        }
    },
    "football": {
        "emoji": "⚽", "name": "Футбол", "choices": {
            "goal": {"name": "Гол", "x": 2},
            "miss": {"name": "Промах", "x": 2},
        }
    },
    "basketball": {
        "emoji": "🏀", "name": "Баскетбол", "choices": {
            "goal": {"name": "Гол", "x": 2},
            "miss": {"name": "Промах", "x": 2},
        }
    },
    "darts": {
        "emoji": "🎯", "name": "Сектор",
        "rows": [["center", "red"], ["bounce", "white"], ["any_sector"], ["red_or_center"], ["white_or_bounce"]],
        "choices": {
            "center":          {"name": "🎯 Центр", "x": 6},
            "red":             {"name": "🔴 Сектор", "x": 3},
            "bounce":          {"name": "🎯 Отскок", "x": 6},
            "white":           {"name": "⚪ Сектор", "x": 3},
            "any_sector":      {"name": "Любой сектор", "x": 1.5},
            "red_or_center":   {"name": "🔴 Сектор или Центр", "x": 2},
            "white_or_bounce": {"name": "⚪ Сектор или Отскок", "x": 2},
        }
    },
    "bowling": {
        "emoji": "🎳", "name": "Боулинг",
        "rows": [["strike", "miss"], ["p1", "p3"], ["p4", "p5"]],
        "choices": {
            "strike": {"name": "🎳 Страйк", "x": 6},
            "miss":   {"name": "🎳 Промах", "x": 6},
            "p1":     {"name": "🎳 Сбито 1/6", "x": 6},
            "p3":     {"name": "🎳 Сбито 3/6", "x": 6},
            "p4":     {"name": "🎳 Сбито 4/6", "x": 6},
            "p5":     {"name": "🎳 Сбито 5/6", "x": 6},
        }
    },
    "slot": {
        "emoji": "🎰", "name": "777", "choices": {
            "777": {"name": "777 (Джекпот)", "x": 10},
        }
    },
}

session_state = {}


def get_user(uid, username=None):
    return db_get_user(uid, username)


def get_display_name(uid, u):
    return u.get("username", f"Player{uid % 10000}")


def bottom_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="🎮 Играть")],
            [KeyboardButton(text="☰ Меню"), KeyboardButton(text="🏆 Топ")],
        ],
        resize_keyboard=True
    )


def main_menu(uid):
    buttons = [
        [
            InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"),
            InlineKeyboardButton(text="⚽ Футбол", callback_data="game_football"),
            InlineKeyboardButton(text="🏀 Баскетбол", callback_data="game_basketball"),
        ],
        [
            InlineKeyboardButton(text="🎯 Сектор", callback_data="game_darts"),
            InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowling"),
            InlineKeyboardButton(text="🎰 777", callback_data="game_slot"),
        ],
        [InlineKeyboardButton(text="👑 Авторские", callback_data="author_games")],
        [
            InlineKeyboardButton(text="🎁 Раздачи ↗", url=CHAT_LINK),
            InlineKeyboardButton(text="💬 Игровой чат ↗", url=CHAT_LINK),
        ],
        [
            InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit"),
            InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw"),
        ],
    ]
    if uid == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton(text="👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def menu_text(uid):
    u = get_user(uid)
    return (
        f"🎮 <b>Выберите игру, на которую хотите сделать ставку!</b>\n\n"
        f"💵 Баланс: <b>{u['balance']}$</b>"
    )


def game_menu(uid, game_key):
    g = GAMES[game_key]
    buttons = []
    if "rows" in g:
        for row in g["rows"]:
            btn_row = []
            for choice_key in row:
                choice = g["choices"][choice_key]
                btn_row.append(InlineKeyboardButton(
                    text=f"{choice['name']} (x{choice['x']})",
                    callback_data=f"choice_{game_key}_{choice_key}"
                ))
            buttons.append(btn_row)
    else:
        for choice_key, choice in g["choices"].items():
            buttons.append([InlineKeyboardButton(
                text=f"{choice['name']} (x{choice['x']})",
                callback_data=f"choice_{game_key}_{choice_key}"
            )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    uid = m.from_user.id
    username = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
    u = get_user(uid, username)

    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            ref_id = int(args[1].replace("ref", ""))
            if ref_id != uid and u["ref"] is None:
                db_update_user(uid, ref=ref_id)
                ref_user = get_user(ref_id)
                db_update_user(ref_id, refs=ref_user["refs"] + 1)
                try:
                    await bot.send_message(ref_id, "🎉 Новый реферал! +10% с пополнений")
                except:
                    pass
        except:
            pass

    await m.answer(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")
    await m.answer("Меню 👇", reply_markup=bottom_menu())


# ==================== РОЗЫГРЫШ ====================
@dp.message(Command("giveaway"))
async def cmd_giveaway(m: types.Message):
    """Админ розыгрыш жасайды: /giveaway <сома> <мин_депозит>"""
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return

    args = m.text.split()
    if len(args) < 3:
        await m.answer(
            "📋 <b>Использование:</b>\n\n"
            "<code>/giveaway 10 3</code>\n\n"
            "• 10 — призовой фонд ($)\n"
            "• 3 — минимальная сумма пополнений ($)",
            parse_mode="HTML"
        )
        return

    try:
        amount = float(args[1])
        min_dep = float(args[2])
    except:
        await m.answer("❌ Неверный формат")
        return

    gid = next_gid[0]
    next_gid[0] += 1

    giveaways[gid] = {
        "amount": amount,
        "min_dep": min_dep,
        "participants": [],
        "active": True,
    }

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Участвовать", callback_data=f"gjoin_{gid}")]
    ])

    msg = await m.answer(
        f"🎉 <b>РОЗЫГРЫШ!</b>\n\n"
        f"💰 Призовой фонд: <b>{amount}$</b>\n"
        f"📋 Минимум пополнений: <b>{min_dep}$</b>\n\n"
        f"❗ Чтобы участвовать, у вас должно быть пополнений на сумму не менее <b>{min_dep}$</b>\n\n"
        f"👇 Нажмите кнопку для участия:",
        reply_markup=kb, parse_mode="HTML"
    )

    giveaways[gid]["chat_id"] = msg.chat.id
    giveaways[gid]["msg_id"] = msg.message_id

    if CHANNEL_ID:
        try:
            await bot.send_message(
                CHANNEL_ID,
                f"🎉 <b>РОЗЫГРЫШ!</b>\n\n"
                f"💰 Призовой фонд: <b>{amount}$</b>\n"
                f"📋 Минимум пополнений: <b>{min_dep}$</b>\n\n"
                f"Участвуйте в боте!",
                parse_mode="HTML"
            )
        except:
            pass


@dp.callback_query(F.data.startswith("gjoin_"))
async def cb_giveaway_join(cb: types.CallbackQuery):
    gid = int(cb.data.replace("gjoin_", ""))
    if gid not in giveaways or not giveaways[gid]["active"]:
        await cb.answer("❌ Розыгрыш завершён или не найден!")
        return

    g = giveaways[gid]
    uid = cb.from_user.id
    username = f"@{cb.from_user.username}" if cb.from_user.username else cb.from_user.first_name
    u = get_user(uid, username)

    # Тексеру: бұрын қатысқан ба?
    if uid in g["participants"]:
        await cb.answer("⚠️ Вы уже участвуете!", show_alert=True)
        return

    # Тексеру: жеткілікті депозит бар ма?
    if u["total_deposit"] < g["min_dep"]:
        await cb.answer(
            f"❌ Недостаточно пополнений!\n\n"
            f"Нужно: {g['min_dep']}$\n"
            f"У вас: {round(u['total_deposit'], 2)}$",
            show_alert=True
        )
        return

    # Қосу
    g["participants"].append(uid)
    await cb.answer("✅ Вы успешно участвуете! Удачи!", show_alert=True)

    # Админге хабарлау
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🎁 <b>Новый участник розыгрыша!</b>\n\n"
            f"👤 {username}\n"
            f"💰 Пополнений: {round(u['total_deposit'], 2)}$\n"
            f"👥 Всего участников: {len(g['participants'])}",
            parse_mode="HTML"
        )
    except:
        pass


@dp.message(Command("endgiveaway"))
async def cmd_endgiveaway(m: types.Message):
    """Админ розыгрышты аяқтайды: /endgiveaway <gid>"""
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return

    args = m.text.split()
    if len(args) < 2:
        # Егер gid көрсетілмесе — соңғы белсенді розыгрышты аяқтау
        active_gids = [gid for gid, g in giveaways.items() if g["active"]]
        if not active_gids:
            await m.answer("❌ Белсенді розыгрыш жоқ")
            return
        gid = active_gids[-1]
    else:
        try:
            gid = int(args[1])
        except:
            await m.answer("❌ Неверный формат: /endgiveaway <gid>")
            return

    if gid not in giveaways:
        await m.answer("❌ Розыгрыш табылмады")
        return

    g = giveaways[gid]
    if not g["active"]:
        await m.answer("❌ Розыгрыш уже завершён")
        return

    if not g["participants"]:
        g["active"] = False
        await m.answer("❌ Никто не участвовал в розыгрыше")
        return

    # Кездейсоқ жеңімпаз
    winner_uid = random.choice(g["participants"])
    winner = get_user(winner_uid)
    winner_name = get_display_name(winner_uid, winner)

    # Балансына қосу
    new_balance = round(winner["balance"] + g["amount"], 2)
    db_update_user(winner_uid, balance=new_balance)

    g["active"] = False

    await m.answer(
        f"🎉 <b>РОЗЫГРЫШ ЗАВЕРШЁН!</b>\n\n"
        f"💰 Приз: <b>{g['amount']}$</b>\n"
        f"👥 Участников: <b>{len(g['participants'])}</b>\n\n"
        f"🏆 <b>ПОБЕДИТЕЛЬ: {winner_name}</b>\n"
        f"💰 Новый баланс: <b>{new_balance}$</b>",
        parse_mode="HTML"
    )

    # Жеңімпазға хабарлау
    try:
        await bot.send_message(
            winner_uid,
            f"🎉 <b>ПОЗДРАВЛЯЕМ!</b>\n\n"
            f"🏆 Вы выиграли розыгрыш!\n"
            f"💰 Приз: <b>+{g['amount']}$</b>\n"
            f"💵 Новый баланс: <b>{new_balance}$</b>",
            parse_mode="HTML"
        )
    except:
        pass

    # Каналға жариялау
    if CHANNEL_ID:
        try:
            await bot.send_message(
                CHANNEL_ID,
                f"🎉 <b>РОЗЫГРЫШ ЗАВЕРШЁН!</b>\n\n"
                f"💰 Приз: <b>{g['amount']}$</b>\n"
                f"🏆 Победитель: <b>{winner_name}</b>\n\n"
                f"🎊 Поздравляем!",
                parse_mode="HTML"
            )
        except:
            pass


@dp.message(Command("giveaways"))
async def cmd_giveaways(m: types.Message):
    """Белсенді розыгрыштар тізімі"""
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return

    active = [(gid, g) for gid, g in giveaways.items() if g["active"]]
    if not active:
        await m.answer("📭 Белсенді розыгрыштар жоқ")
        return

    text = "🎁 <b>АКТИВНЫЕ РОЗЫГРЫШИ</b>\n\n"
    for gid, g in active:
        text += (
            f"<b>ID {gid}</b>\n"
            f"💰 Приз: {g['amount']}$\n"
            f"📋 Мин. депозит: {g['min_dep']}$\n"
            f"👥 Участников: {len(g['participants'])}\n\n"
        )

    text += "Аяқтау үшін: <code>/endgiveaway ID</code>"
    await m.answer(text, parse_mode="HTML")


# ==================== АДМИН БОНУС ====================
@dp.message(Command("bonus"))
async def cmd_bonus(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return

    args = m.text.split()

    if m.reply_to_message:
        if len(args) < 2:
            await m.answer("❌ Использование: <code>/bonus 10</code>", parse_mode="HTML")
            return
        try:
            amount = float(args[1])
        except:
            await m.answer("❌ Неверная сумма")
            return
        target_user = m.reply_to_message.from_user
        target_uid = target_user.id
        target_name = f"@{target_user.username}" if target_user.username else target_user.first_name
        tu = get_user(target_uid, target_name)
        new_bal = round(tu["balance"] + amount, 2)
        db_update_user(target_uid, balance=new_bal)
        await m.answer(
            f"✅ <b>Бонус выдан!</b>\n\n👤 <b>{target_name}</b>\n➕ +{amount}$\n💰 {new_bal}$",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(target_uid, f"🎁 <b>Вам выдан бонус!</b>\n\n➕ <b>+{amount}$</b>\n💰 Баланс: <b>{new_bal}$</b>", parse_mode="HTML")
        except:
            pass
        return

    if len(args) < 3:
        await m.answer(
            "📋 <b>Использование:</b>\n\n"
            "1️⃣ Ответом: <code>/bonus 10</code>\n"
            "2️⃣ По username: <code>/bonus @username 10</code>",
            parse_mode="HTML"
        )
        return

    target_username = args[1]
    if not target_username.startswith("@"):
        await m.answer("❌ Username @ арқылы басталуы керек")
        return

    try:
        amount = float(args[2])
    except:
        await m.answer("❌ Неверная сумма")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT uid, username, balance FROM users WHERE LOWER(username) = ?", (target_username.lower(),))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        await m.answer(f"❌ Пользователь <b>{target_username}</b> не найден!", parse_mode="HTML")
        return

    target_uid, target_name, target_balance = row
    new_balance = round(target_balance + amount, 2)
    db_update_user(target_uid, balance=new_balance)
    await m.answer(
        f"✅ <b>Бонус выдан!</b>\n\n👤 <b>{target_name}</b>\n➕ +{amount}$\n💰 {new_balance}$",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(target_uid, f"🎁 <b>Вам выдан бонус!</b>\n\n➕ <b>+{amount}$</b>\n💰 Баланс: <b>{new_balance}$</b>", parse_mode="HTML")
    except:
        pass


# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать бонус", callback_data="admin_bonus")],
        [InlineKeyboardButton(text="🎉 Розыгрыштар", callback_data="admin_giveaways")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все игроки", callback_data="admin_users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="top_refs")],
        [InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance")],
        [InlineKeyboardButton(text="🎮 Топ игроков", callback_data="top_players")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])
    await cb.message.answer("👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "admin_giveaways")
async def cb_admin_giveaways(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    active = [(gid, g) for gid, g in giveaways.items() if g["active"]]
    text = "🎉 <b>РОЗЫГРЫШИ</b>\n\n"
    if not active:
        text += "Активных розыгрышей нет\n\n"
    else:
        for gid, g in active:
            text += f"<b>ID {gid}</b> — {g['amount']}$ | {len(g['participants'])} участников\n"
    text += (
        "\n<b>Команды:</b>\n"
        "<code>/giveaway 10 3</code> — жасау\n"
        "<code>/giveaways</code> — тізім\n"
        "<code>/endgiveaway ID</code> — аяқтау"
    )
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "admin_bonus")
async def cb_admin_bonus(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    await cb.message.answer(
        "🎁 <b>Выдача бонуса</b>\n\n"
        "1️⃣ Ответом: <code>/bonus 10</code>\n"
        "2️⃣ По username: <code>/bonus @username 10</code>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(balance), SUM(refs), SUM(games_played), SUM(total_bets), SUM(total_deposit) FROM users")
    row = cursor.fetchone()
    conn.close()
    active_gw = len([g for g in giveaways.values() if g["active"]])
    await cb.message.answer(
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"👥 Игроков: <b>{row[0] or 0}</b>\n"
        f"💰 Общий баланс: <b>{round(row[1] or 0, 2)}$</b>\n"
        f"💳 Всего пополнений: <b>{round(row[5] or 0, 2)}$</b>\n"
        f"👥 Рефералов: <b>{row[2] or 0}</b>\n"
        f"🎮 Игр: <b>{row[3] or 0}</b>\n"
        f"💵 Ставок: <b>{round(row[4] or 0, 2)}$</b>\n"
        f"🎉 Розыгрышей: <b>{active_gw}</b>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT uid, username, balance, refs, total_deposit FROM users ORDER BY balance DESC LIMIT 30")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await cb.message.answer("📭 Игроков нет")
        await cb.answer()
        return
    text = "👥 <b>ВСЕ ИГРОКИ</b>\n\n"
    for i, (uid, username, balance, refs, dep) in enumerate(rows, 1):
        text += f"{i}. <b>{username}</b>\n   💰 {balance}$ | 💳 {round(dep, 2)}$ | 👥 {refs}\n"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    await cb.message.answer("📢 <b>Рассылка</b>\n\n<code>/send Текст</code>", parse_mode="HTML")
    await cb.answer()


@dp.message(Command("send"))
async def cmd_send(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return
    text = m.text.replace("/send ", "", 1).strip()
    if not text or text == "/send":
        await m.answer("❌ Использование: <code>/send Текст</code>", parse_mode="HTML")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM users")
    uids = [r[0] for r in cursor.fetchall()]
    conn.close()
    success, failed = 0, 0
    for uid in uids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await m.answer(f"✅ Отправлено: <b>{success}</b>\n❌ Ошибок: <b>{failed}</b>", parse_mode="HTML")


# ==================== ТОПТАР ====================
@dp.callback_query(F.data == "top_refs")
async def cb_top_refs(cb: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, refs FROM users WHERE refs > 0 ORDER BY refs DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    text = "🏆 <b>ТОП РЕФЕРАЛОВ</b>\n\n"
    if not rows:
        text += "Пока никого нет"
    else:
        for i, (username, refs) in enumerate(rows, 1):
            text += f"{i}. <b>{username}</b> — 👥 {refs}\n"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, balance FROM users WHERE balance > 0 ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    text = "💰 <b>ТОП ПО БАЛАНСУ</b>\n\n"
    if not rows:
        text += "Пока никого нет"
    else:
        for i, (username, balance) in enumerate(rows, 1):
            text += f"{i}. <b>{username}</b> — 💰 {round(balance, 2)}$\n"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "top_players")
async def cb_top_players(cb: types.CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, games_played, total_bets FROM users WHERE total_bets > 0 ORDER BY total_bets DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    text = "🎮 <b>ТОП ИГРОКОВ</b>\n\n"
    if not rows:
        text += "Пока никого нет"
    else:
        for i, (username, games, bets) in enumerate(rows, 1):
            text += f"{i}. <b>{username}</b>\n   🎮 {games} | 💵 {round(bets, 2)}$\n"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


# ==================== REPLY BUTTONS ====================
@dp.message(F.text == "💰 Баланс")
async def btn_balance(m: types.Message):
    uid = m.from_user.id
    username = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
    u = get_user(uid, username)
    await m.answer(
        f"💰 <b>Баланс:</b> {u['balance']}$\n"
        f"💳 <b>Пополнений:</b> {round(u['total_deposit'], 2)}$\n"
        f"👥 <b>Рефералов:</b> {u['refs']}",
        parse_mode="HTML"
    )


@dp.message(F.text == "🎮 Играть")
async def btn_play(m: types.Message):
    uid = m.from_user.id
    username = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
    get_user(uid, username)
    await m.answer(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")


@dp.message(F.text == "🏆 Топ")
async def btn_top(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="top_refs")],
        [InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance")],
        [InlineKeyboardButton(text="🎮 Топ игроков", callback_data="top_players")],
    ])
    await m.answer("🏆 <b>Топы</b>", reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "☰ Меню")
async def btn_menu(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref_link")],
        [InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit")],
        [InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw")],
    ])
    await m.answer("☰ <b>Меню</b>", reply_markup=kb, parse_mode="HTML")


# ==================== GAME MENU ====================
@dp.callback_query(F.data.startswith("game_"))
async def cb_game(cb: types.CallbackQuery):
    game_key = cb.data.replace("game_", "")
    if game_key not in GAMES:
        await cb.answer("Ошибка!")
        return
    g = GAMES[game_key]
    await cb.message.answer(
        f"{g['emoji']} <b>{g['name']}</b>\n\nВыберите тип ставки:",
        reply_markup=game_menu(cb.from_user.id, game_key),
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "back_menu")
async def cb_back(cb: types.CallbackQuery):
    session_state.setdefault(cb.from_user.id, {})
    session_state[cb.from_user.id]["pending_game"] = None
    await cb.message.edit_text(menu_text(cb.from_user.id), reply_markup=main_menu(cb.from_user.id), parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("choice_"))
async def cb_choice(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Ошибка!")
        return
    game_key, choice_key = parts[1], parts[2]
    if game_key not in GAMES or choice_key not in GAMES[game_key]["choices"]:
        await cb.answer("Ошибка!")
        return
    choice = GAMES[game_key]["choices"][choice_key]
    uid = cb.from_user.id
    u = get_user(uid)
    session_state.setdefault(uid, {})
    session_state[uid]["pending_game"] = {"game_key": game_key, "choice_key": choice_key}
    await cb.message.answer(
        f"{GAMES[game_key]['emoji']} <b>{GAMES[game_key]['name']} — {choice['name']}</b>\n"
        f"Коэффициент: <b>x{choice['x']}</b>\n\n"
        f"💵 Баланс: <b>{u['balance']}$</b>\n\n"
        f"✏️ <b>Введите сумму ставки:</b>\nМин: <b>{BET_MIN}$</b>\nМакс: <b>{BET_MAX}$</b>",
        parse_mode="HTML"
    )
    await cb.answer()


# ==================== ОЙЫН ====================
async def play_game(message, uid, game_key, choice_key, bet):
    user = message.from_user
    nick = f"@{user.username}" if user.username else user.first_name
    u = get_user(uid, nick)
    g = GAMES[game_key]
    choice = g["choices"][choice_key]

    if CHANNEL_ID:
        try:
            await bot.send_message(
                CHANNEL_ID,
                f"🎰 <b>{nick}</b> поставил <b>{bet}$</b>\nна <b>{g['name']} — {choice['name']}</b> (x{choice['x']})",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Канал қатесі: {e}")

    dice_msg = await message.answer_dice(emoji=g["emoji"])
    await asyncio.sleep(4)

    if CHANNEL_ID:
        try:
            await dice_msg.forward(chat_id=CHANNEL_ID)
        except Exception as e:
            print(f"Forward қатесі: {e}")

    result = dice_msg.dice.value
    is_win, result_text = check_win(game_key, choice_key, result)

    new_total_bets = round(u.get("total_bets", 0) + bet, 2)
    new_games = u.get("games_played", 0) + 1

    if is_win:
        win = round(bet * choice["x"], 2)
        new_balance = round(u["balance"] - bet + win, 2)
        new_total_won = round(u.get("total_won", 0) + win, 2)
        db_update_user(uid, balance=new_balance, total_bets=new_total_bets, games_played=new_games, total_won=new_total_won)
        text = (
            f"🎉 <b>ПОБЕДА!</b>\n\n{g['emoji']} {g['name']} — {choice['name']}\n"
            f"<i>{result_text}</i>\n\n➕ Выигрыш: <b>+{win}$</b>\n💰 Баланс: <b>{new_balance}$</b>"
        )
        channel_text = (
            f"✅ <b>ВЫИГРЫШ!</b>\n\n👤 <b>{nick}</b>\n"
            f"🎮 {g['emoji']} {g['name']} — {choice['name']}\n"
            f"🎲 {result}\n💵 Ставка: {bet}$\n➕ Выигрыш: +{win}$ (x{choice['x']})"
        )
    else:
        new_balance = round(u["balance"] - bet, 2)
        db_update_user(uid, balance=new_balance, total_bets=new_total_bets, games_played=new_games)
        text = (
            f"😢 <b>ПРОИГРЫШ</b>\n\n{g['emoji']} {g['name']} — {choice['name']}\n"
            f"<i>{result_text}</i>\n\n➖ Проигрыш: <b>-{bet}$</b>\n💰 Баланс: <b>{new_balance}$</b>"
        )
        channel_text = (
            f"❌ <b>ПРОИГРЫШ</b>\n\n👤 <b>{nick}</b>\n"
            f"🎮 {g['emoji']} {g['name']} — {choice['name']}\n"
            f"🎲 {result}\n💵 Ставка: {bet}$\n➖ Проигрыш: -{bet}$"
        )

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu(uid))

    if CHANNEL_ID:
        try:
            await bot.send_message(CHANNEL_ID, channel_text, parse_mode="HTML")
        except Exception as e:
            print(f"Канал нәтиже қатесі: {e}")


def check_win(game_key, choice_key, result):
    text, win = "", False

    if game_key == "dice":
        if choice_key == "more3": win = result >= 4; text = f"Выпало {result} → {'больше 3 ✅' if win else 'НЕ больше 3 ❌'}"
        elif choice_key == "less3": win = result <= 3; text = f"Выпало {result} → {'меньше 3 ✅' if win else 'НЕ меньше 3 ❌'}"
        elif choice_key == "even": win = result % 2 == 0; text = f"Выпало {result} → {'чётное ✅' if win else 'НЕчётное ❌'}"
        elif choice_key == "odd": win = result % 2 == 1; text = f"Выпало {result} → {'нечётное ✅' if win else 'Чётное ❌'}"

    elif game_key == "football":
        is_goal = result >= 3
        if choice_key == "goal": win = is_goal; text = f"Выпало {result} → {'ГОЛ ✅' if win else 'Промах ❌'}"
        elif choice_key == "miss": win = not is_goal; text = f"Выпало {result} → {'Промах ✅' if win else 'ГОЛ ❌'}"

    elif game_key == "basketball":
        is_goal = result >= 3
        if choice_key == "goal": win = is_goal; text = f"Выпало {result} → {'ГОЛ ✅' if win else 'Промах ❌'}"
        elif choice_key == "miss": win = not is_goal; text = f"Выпало {result} → {'Промах ✅' if win else 'ГОЛ ❌'}"

    elif game_key == "darts":
        if choice_key == "center": win = result == 6; text = f"Выпало {result} → {'ЦЕНТР ✅' if win else 'Не центр ❌'}"
        elif choice_key == "red": win = result in [4, 5]; text = f"Выпало {result} → {'Красный ✅' if win else 'Не красный ❌'}"
        elif choice_key == "white": win = result in [2, 3]; text = f"Выпало {result} → {'Белый ✅' if win else 'Не белый ❌'}"
        elif choice_key == "bounce": win = result == 1; text = f"Выпало {result} → {'Отскок ✅' if win else 'Не отскок ❌'}"
        elif choice_key == "any_sector": win = result in [2, 3, 4, 5]; text = f"Выпало {result} → {'Любой сектор ✅' if win else 'Не сектор ❌'}"
        elif choice_key == "red_or_center": win = result in [4, 5, 6]; text = f"Выпало {result} → {'✅' if win else '❌'}"
        elif choice_key == "white_or_bounce": win = result in [1, 2, 3]; text = f"Выпало {result} → {'✅' if win else '❌'}"

    elif game_key == "bowling":
        if choice_key == "strike": win = result == 6; text = f"{result} → {'СТРАЙК ✅' if win else '❌'}"
        elif choice_key == "miss": win = result == 1; text = f"{result} → {'Промах ✅' if win else '❌'}"
        elif choice_key == "p1": win = result == 1; text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p3": win = result == 3; text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p4": win = result == 4; text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p5": win = result == 5; text = f"Сбито {result}/6 → {'✅' if win else '❌'}"

    elif game_key == "slot":
        if choice_key == "777": win = result == 64; text = f"{result} → {'ДЖЕКПОТ ✅' if win else '❌'}"

    return win, text


# ==================== DEPOSIT ====================
@dp.callback_query(F.data == "deposit")
async def cb_deposit(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1$", callback_data="dep_1")],
        [InlineKeyboardButton(text="5$", callback_data="dep_5")],
        [InlineKeyboardButton(text="10$", callback_data="dep_10")],
        [InlineKeyboardButton(text="✏️ Другая", callback_data="dep_custom")],
    ])
    await cb.message.answer("💳 <b>Пополнение</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("dep_"))
async def cb_dep_amount(cb: types.CallbackQuery):
    data = cb.data.replace("dep_", "")
    uid = cb.from_user.id
    if data == "custom":
        session_state.setdefault(uid, {})
        session_state[uid]["await_dep"] = True
        await cb.message.answer("✏️ Введите сумму (1-10000$):")
        await cb.answer()
        return
    await create_deposit_invoice(cb.message, uid, float(data))
    await cb.answer()


async def create_deposit_invoice(message, uid, amount):
    if crypto is None:
        await message.answer("❌ CryptoPay недоступен")
        return
    try:
        invoice = await crypto.create_invoice(
            asset="USDT", amount=amount, description="Пополнение",
            payload=f"dep_{uid}_{amount}", expires_in=1800,
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_{invoice.invoice_id}_{amount}")],
        ])
        await message.answer(f"💳 <b>Счёт на {amount}$</b>", reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.callback_query(F.data.startswith("check_"))
async def cb_check(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    invoice_id, amount, uid = int(parts[1]), float(parts[2]), cb.from_user.id
    try:
        inv = await crypto.get_invoices(invoice_ids=invoice_id)
        if isinstance(inv, list):
            inv = inv[0] if inv else None
        if inv and inv.status == "paid":
            u = get_user(uid)
            new_balance = round(u["balance"] + amount, 2)
            new_dep = round(u.get("total_deposit", 0) + amount, 2)
            db_update_user(uid, balance=new_balance, total_deposit=new_dep)
            await cb.message.answer(
                f"✅ <b>Баланс пополнен!</b>\n➕ +{amount}$\n💰 {new_balance}$\n💳 Всего пополнений: {new_dep}$",
                parse_mode="HTML"
            )
            referrer_id = u.get("ref")
            if referrer_id:
                bonus = round(amount * REF_PERCENT, 2)
                ref_user = get_user(referrer_id)
                ref_new_balance = round(ref_user["balance"] + bonus, 2)
                db_update_user(referrer_id, balance=ref_new_balance)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"💸 <b>Реферальный бонус!</b>\n\n👤 {u.get('username', '?')} пополнил на <b>{amount}$</b>\n➕ Вам: <b>+{bonus}$</b>\n💰 {ref_new_balance}$",
                        parse_mode="HTML"
                    )
                except:
                    pass
            try:
                await bot.send_message(ADMIN_ID, f"💳 Пополнение: {u.get('username', '?')} — {amount}$")
            except:
                pass
        else:
            await cb.message.answer("⏳ Ещё не подтверждён.")
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка: {e}")
    await cb.answer()


# ==================== WITHDRAW ====================
@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = get_user(uid)
    if u["balance"] < WITHDRAW_MIN:
        await cb.message.answer(f"❌ Минимум для вывода: {WITHDRAW_MIN}$\n💰 Баланс: {u['balance']}$", parse_mode="HTML")
        await cb.answer()
        return
    session_state.setdefault(uid, {})
    session_state[uid]["await_withdraw"] = True
    await cb.message.answer(
        f"📤 <b>Вывод</b>\n\n💰 {u['balance']}$\nМин: {WITHDRAW_MIN}$\n\n✏️ Введите сумму:",
        parse_mode="HTML"
    )
    await cb.answer()


# ==================== PROFILE ====================
@dp.callback_query(F.data == "profile")
async def cb_profile(cb: types.CallbackQuery):
    uid = cb.from_user.id
    username = f"@{cb.from_user.username}" if cb.from_user.username else cb.from_user.first_name
    u = get_user(uid, username)
    await cb.message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"📛 <b>{u['username']}</b>\n"
        f"💰 Баланс: <b>{u['balance']}$</b>\n"
        f"💳 Пополнений: <b>{round(u['total_deposit'], 2)}$</b>\n"
        f"👥 Рефералов: <b>{u['refs']}</b>\n"
        f"🎮 Игр: <b>{u.get('games_played', 0)}</b>\n"
        f"💵 Ставок: <b>{round(u.get('total_bets', 0), 2)}$</b>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "ref_link")
async def cb_ref(cb: types.CallbackQuery):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{cb.from_user.id}"
    u = get_user(cb.from_user.id)
    await cb.message.answer(
        f"👥 <b>Пригласите друга — 10% с пополнений!</b>\n\n🔗 <code>{link}</code>\n\n👥 Рефералов: <b>{u['refs']}</b>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "author_games")
async def cb_author(cb: types.CallbackQuery):
    await cb.message.answer("👑 <b>Авторские игры</b>\n\nСкоро!", parse_mode="HTML")
    await cb.answer()


# ==================== TEXT ====================
@dp.message(F.text.regexp(r"^\d+(\.\d+)?$"))
async def set_number(m: types.Message):
    uid = m.from_user.id
    username = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
    u = get_user(uid, username)
    val = float(m.text)
    state = session_state.get(uid, {})

    if state.get("pending_game"):
        pg = state["pending_game"]
        game_key, choice_key = pg["game_key"], pg["choice_key"]
        if val < BET_MIN: await m.answer(f"❌ Мин: {BET_MIN}$"); return
        if val > BET_MAX: await m.answer(f"❌ Макс: {BET_MAX}$"); return
        if val > u["balance"]:
            await m.answer(f"❌ Недостаточно средств! Нужно: {val}$\nУ вас: {u['balance']}$", parse_mode="HTML")
            return
        state["pending_game"] = None
        await play_game(m, uid, game_key, choice_key, val)
        return

    if state.get("await_dep"):
        if val < 1: await m.answer("❌ Мин: 1$"); return
        if val > 10000: await m.answer("❌ Макс: 10000$"); return
        state["await_dep"] = False
        await create_deposit_invoice(m, uid, val)
        return

    if state.get("await_withdraw"):
        state["await_withdraw"] = False
        if val < WITHDRAW_MIN: await m.answer(f"❌ Мин: {WITHDRAW_MIN}$"); return
        if val > u["balance"]: await m.answer(f"❌ Недостаточно! Баланс: {u['balance']}$"); return
        if crypto is None: await m.answer("❌ CryptoPay недоступен"); return
        await m.answer("⏳ Создаём чек...")
        try:
            check = await crypto.create_check(asset="USDT", amount=round(val, 2), pin_to_user_id=uid)
            new_balance = round(u["balance"] - val, 2)
            db_update_user(uid, balance=new_balance)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💵 Получить чек", url=check.bot_check_url)],
            ])
            await m.answer(
                f"✅ <b>Чек создан!</b>\n\n💰 {val}$\n💵 Баланс: {new_balance}$\n\n🎁 Активируйте 👇",
                reply_markup=kb, parse_mode="HTML"
            )
            try:
                await bot.send_message(ADMIN_ID, f"📤 Вывод: {username} — {val}$\n🔗 {check.bot_check_url}")
            except:
                pass
        except Exception as e:
            await m.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        return


# ==================== MAIN ====================
async def main():
    db_init()
    print("=" * 40)
    print("🤖 Бот запущен!")
    me = await bot.get_me()
    print("Бот:", me.username)
    print("Канал:", CHANNEL_ID)
    print("=" * 40)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹ Остановлен.")
    except Exception as e:
        print(f"\n❌ КАТЕ: {e}")
        traceback.print_exc()
