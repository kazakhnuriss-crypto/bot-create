import asyncio
import logging
import traceback
import os
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

users = {}
# {uid: "username"} — username-нен uid-ке
username_index = {}


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
        "rows": [
            ["center", "red"],
            ["bounce", "white"],
            ["any_sector"],
            ["red_or_center"],
            ["white_or_bounce"],
        ],
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
        "rows": [
            ["strike", "miss"],
            ["p1", "p3"],
            ["p4", "p5"],
        ],
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


def get_user(uid, username=None):
    if uid not in users:
        users[uid] = {
            "balance": 0.0,
            "username": username or f"Player{uid % 10000}",
            "ref": None,
            "refs": 0,
            "total_bets": 0.0,
            "games_played": 0,
            "total_won": 0.0,
            "await_dep": False,
            "await_withdraw": False,
            "pending_game": None,
        }
    elif username:
        users[uid]["username"] = username
    # username индексін жаңарту
    if users[uid].get("username"):
        username_index[users[uid]["username"].lower().replace("@", "")] = uid
    return users[uid]


def find_user_by_username(username):
    """Username арқылы пайдаланушыны табу"""
    username_clean = username.lower().replace("@", "").strip()
    # Тікелей индекстен
    if username_clean in username_index:
        uid = username_index[username_clean]
        return uid, users.get(uid)
    # Іздеу
    for uid, u in users.items():
        u_name = u.get("username", "").lower().replace("@", "")
        if u_name == username_clean:
            return uid, u
    return None, None


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
            if ref_id != uid:
                if u["ref"] is None:
                    u["ref"] = ref_id
                    get_user(ref_id)["refs"] += 1
                    try:
                        await bot.send_message(ref_id, "🎉 Новый реферал! +10% с пополнений")
                    except:
                        pass
        except:
            pass

    await m.answer(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")
    await m.answer("Меню 👇", reply_markup=bottom_menu())


# ==================== АДМИН БОНУС ====================
@dp.message(Command("bonus"))
async def cmd_bonus(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        await m.answer("❌ У вас нет прав!")
        return

    args = m.text.split()

    # ===== REPLY арқылы =====
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

        get_user(target_uid, target_name)["balance"] = round(get_user(target_uid)["balance"] + amount, 2)

        await m.answer(
            f"✅ <b>Бонус выдан!</b>\n\n"
            f"👤 Игрок: <b>{target_name}</b>\n"
            f"➕ Сумма: <b>+{amount}$</b>\n"
            f"💰 Баланс: <b>{get_user(target_uid)['balance']}$</b>",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                target_uid,
                f"🎁 <b>Вам выдан бонус!</b>\n\n"
                f"➕ <b>+{amount}$</b>\n"
                f"💰 Баланс: <b>{get_user(target_uid)['balance']}$</b>",
                parse_mode="HTML"
            )
        except:
            pass
        return

    # ===== @username арқылы =====
    if len(args) < 3:
        await m.answer(
            "📋 <b>Использование:</b>\n\n"
            "1️⃣ Ответом на сообщение:\n"
            "<code>/bonus 10</code>\n\n"
            "2️⃣ По username:\n"
            "<code>/bonus @username 10</code>",
            parse_mode="HTML"
        )
        return

    target_username = args[1]
    if not target_username.startswith("@"):
        await m.answer("❌ Username @ арқылы басталуы керек\nМысалы: <code>/bonus @AimonKz 10</code>", parse_mode="HTML")
        return

    try:
        amount = float(args[2])
    except:
        await m.answer("❌ Неверная сумма")
        return

    target_uid, target_u = find_user_by_username(target_username)

    if target_uid is None:
        await m.answer(
            f"❌ Пользователь <b>{target_username}</b> не найден!\n\n"
            f"💡 Убедитесь, что он запустил бота (/start)",
            parse_mode="HTML"
        )
        return

    target_u["balance"] = round(target_u["balance"] + amount, 2)
    target_name = target_u["username"]

    await m.answer(
        f"✅ <b>Бонус выдан!</b>\n\n"
        f"👤 Игрок: <b>{target_name}</b>\n"
        f"➕ Сумма: <b>+{amount}$</b>\n"
        f"💰 Баланс: <b>{target_u['balance']}$</b>",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            target_uid,
            f"🎁 <b>Вам выдан бонус!</b>\n\n"
            f"➕ <b>+{amount}$</b>\n"
            f"💰 Баланс: <b>{target_u['balance']}$</b>",
            parse_mode="HTML"
        )
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
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Все игроки", callback_data="admin_users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="top_refs")],
        [InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance")],
        [InlineKeyboardButton(text="🎮 Топ игроков", callback_data="top_players")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])
    await cb.message.answer(
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\nВыберите действие:",
        reply_markup=kb, parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "admin_bonus")
async def cb_admin_bonus(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    await cb.message.answer(
        "🎁 <b>Выдача бонуса</b>\n\n"
        "<b>Способ 1:</b> Ответом на сообщение игрока\n"
        "<code>/bonus 10</code>\n\n"
        "<b>Способ 2:</b> По username\n"
        "<code>/bonus @username 10</code>\n\n"
        "💡 ID не нужен!",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    total_users = len(users)
    total_balance = sum(u["balance"] for u in users.values())
    total_refs = sum(u["refs"] for u in users.values())
    total_bets = sum(u.get("total_bets", 0) for u in users.values())
    total_games = sum(u.get("games_played", 0) for u in users.values())
    await cb.message.answer(
        f"📊 <b>СТАТИСТИКА</b>\n\n"
        f"👥 Игроков: <b>{total_users}</b>\n"
        f"💰 Общий баланс: <b>{round(total_balance, 2)}$</b>\n"
        f"👥 Всего рефералов: <b>{total_refs}</b>\n"
        f"🎮 Всего игр: <b>{total_games}</b>\n"
        f"💵 Всего ставок: <b>{round(total_bets, 2)}$</b>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    if not users:
        await cb.message.answer("📭 Игроков нет")
        await cb.answer()
        return
    text = "👥 <b>ВСЕ ИГРОКИ</b>\n\n"
    for i, (uid, u) in enumerate(users.items(), 1):
        name = get_display_name(uid, u)
        text += f"{i}. <b>{name}</b>\n   💰 {u['balance']}$ | 👥 {u['refs']}\n"
        if i >= 30:
            text += f"\n... и ещё {len(users) - 30}"
            break
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("❌ Нет прав!")
        return
    await cb.message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте: <code>/send Текст сообщения</code>",
        parse_mode="HTML"
    )
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
    success, failed = 0, 0
    for uid in list(users.keys()):
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await m.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{success}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>",
        parse_mode="HTML"
    )


# ==================== ТОПТАР ====================
@dp.callback_query(F.data == "top_refs")
async def cb_top_refs(cb: types.CallbackQuery):
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("refs", 0), reverse=True)[:10]
    text = "🏆 <b>ТОП РЕФЕРАЛОВ</b>\n\n"
    count = 0
    for i, (uid, u) in enumerate(sorted_users, 1):
        if u.get("refs", 0) > 0:
            count += 1
            name = get_display_name(uid, u)
            text += f"{i}. <b>{name}</b> — 👥 {u['refs']}\n"
    if count == 0:
        text += "Пока никого нет"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: types.CallbackQuery):
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("balance", 0), reverse=True)[:10]
    text = "💰 <b>ТОП ПО БАЛАНСУ</b>\n\n"
    count = 0
    for i, (uid, u) in enumerate(sorted_users, 1):
        if u.get("balance", 0) > 0:
            count += 1
            name = get_display_name(uid, u)
            text += f"{i}. <b>{name}</b> — 💰 {round(u['balance'], 2)}$\n"
    if count == 0:
        text += "Пока никого нет"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data == "top_players")
async def cb_top_players(cb: types.CallbackQuery):
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("total_bets", 0), reverse=True)[:10]
    text = "🎮 <b>ТОП ИГРОКОВ</b>\n\n"
    count = 0
    for i, (uid, u) in enumerate(sorted_users, 1):
        if u.get("total_bets", 0) > 0:
            count += 1
            name = get_display_name(uid, u)
            text += (
                f"{i}. <b>{name}</b>\n"
                f"   🎮 {u.get('games_played', 0)} игр | 💵 {round(u['total_bets'], 2)}$\n"
            )
    if count == 0:
        text += "Пока никого нет"
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


# ==================== REPLY BUTTONS ====================
@dp.message(F.text == "💰 Баланс")
async def btn_balance(m: types.Message):
    uid = m.from_user.id
    username = f"@{m.from_user.username}" if m.from_user.username else m.from_user.first_name
    u = get_user(uid, username)
    await m.answer(f"💰 <b>Ваш баланс:</b> {u['balance']}$\n👥 Рефералов: {u['refs']}", parse_mode="HTML")


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
    await m.answer("🏆 <b>Топы</b>\n\nВыберите категорию:", reply_markup=kb, parse_mode="HTML")


@dp.message(F.text == "☰ Меню")
async def btn_menu(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref_link")],
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="top_refs")],
        [InlineKeyboardButton(text="💰 Топ по балансу", callback_data="top_balance")],
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
    u = get_user(cb.from_user.id)
    u["pending_game"] = None
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
    u = get_user(cb.from_user.id)
    u["pending_game"] = {"game_key": game_key, "choice_key": choice_key}
    await cb.message.answer(
        f"{GAMES[game_key]['emoji']} <b>{GAMES[game_key]['name']} — {choice['name']}</b>\n"
        f"Коэффициент: <b>x{choice['x']}</b>\n\n"
        f"💵 Ваш баланс: <b>{u['balance']}$</b>\n\n"
        f"✏️ <b>Введите сумму ставки:</b>\n"
        f"Мин: <b>{BET_MIN}$</b>\nМакс: <b>{BET_MAX}$</b>",
        parse_mode="HTML"
    )
    await cb.answer()


# ==================== ОЙЫН + КАНАЛ ====================
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
                f"🎰 <b>{nick}</b> поставил <b>{bet}$</b>\n"
                f"на <b>{g['name']} — {choice['name']}</b> (x{choice['x']})",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Каналға ставка жіберу қатесі: {e}")

    dice_msg = await message.answer_dice(emoji=g["emoji"])
    await asyncio.sleep(4)

    if CHANNEL_ID:
        try:
            await dice_msg.forward(chat_id=CHANNEL_ID)
        except Exception as e:
            print(f"Каналға дайс forward қатесі: {e}")

    result = dice_msg.dice.value
    is_win, result_text = check_win(game_key, choice_key, result)

    u["total_bets"] = round(u.get("total_bets", 0) + bet, 2)
    u["games_played"] = u.get("games_played", 0) + 1

    if is_win:
        win = round(bet * choice["x"], 2)
        u["balance"] = round(u["balance"] - bet + win, 2)
        u["total_won"] = round(u.get("total_won", 0) + win, 2)
        text = (
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"{g['emoji']} {g['name']} — {choice['name']}\n"
            f"<i>{result_text}</i>\n\n"
            f"➕ Выигрыш: <b>+{win}$</b>\n"
            f"💰 Баланс: <b>{u['balance']}$</b>"
        )
        channel_text = (
            f"✅ <b>ВЫИГРЫШ!</b>\n\n"
            f"👤 <b>{nick}</b>\n"
            f"🎮 {g['emoji']} {g['name']} — {choice['name']}\n"
            f"🎲 Результат: <b>{result}</b>\n"
            f"💵 Ставка: <b>{bet}$</b>\n"
            f"➕ Выигрыш: <b>+{win}$</b> (x{choice['x']})"
        )
    else:
        u["balance"] = round(u["balance"] - bet, 2)
        text = (
            f"😢 <b>ПРОИГРЫШ</b>\n\n"
            f"{g['emoji']} {g['name']} — {choice['name']}\n"
            f"<i>{result_text}</i>\n\n"
            f"➖ Проигрыш: <b>-{bet}$</b>\n"
            f"💰 Баланс: <b>{u['balance']}$</b>"
        )
        channel_text = (
            f"❌ <b>ПРОИГРЫШ</b>\n\n"
            f"👤 <b>{nick}</b>\n"
            f"🎮 {g['emoji']} {g['name']} — {choice['name']}\n"
            f"🎲 Результат: <b>{result}</b>\n"
            f"💵 Ставка: <b>{bet}$</b>\n"
            f"➖ Проигрыш: <b>-{bet}$</b>"
        )

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu(uid))

    if CHANNEL_ID:
        try:
            await bot.send_message(CHANNEL_ID, channel_text, parse_mode="HTML")
        except Exception as e:
            print(f"Каналға нәтиже жіберу қатесі: {e}")


def check_win(game_key, choice_key, result):
    text, win = "", False

    if game_key == "dice":
        if choice_key == "more3":
            win = result >= 4
            text = f"Выпало {result} → {'больше 3 ✅' if win else 'НЕ больше 3 ❌'}"
        elif choice_key == "less3":
            win = result <= 3
            text = f"Выпало {result} → {'меньше 3 ✅' if win else 'НЕ меньше 3 ❌'}"
        elif choice_key == "even":
            win = result % 2 == 0
            text = f"Выпало {result} → {'чётное ✅' if win else 'НЕчётное ❌'}"
        elif choice_key == "odd":
            win = result % 2 == 1
            text = f"Выпало {result} → {'нечётное ✅' if win else 'Чётное ❌'}"

    elif game_key == "football":
        is_goal = result >= 3
        if choice_key == "goal":
            win = is_goal
            text = f"Выпало {result} → {'ГОЛ ✅' if win else 'Промах ❌'}"
        elif choice_key == "miss":
            win = not is_goal
            text = f"Выпало {result} → {'Промах ✅' if win else 'ГОЛ ❌'}"

    elif game_key == "basketball":
        is_goal = result >= 3
        if choice_key == "goal":
            win = is_goal
            text = f"Выпало {result} → {'ГОЛ ✅' if win else 'Промах ❌'}"
        elif choice_key == "miss":
            win = not is_goal
            text = f"Выпало {result} → {'Промах ✅' if win else 'ГОЛ ❌'}"

    elif game_key == "darts":
        if choice_key == "center":
            win = result == 6
            text = f"Выпало {result} → {'ЦЕНТР ✅' if win else 'Не центр ❌'}"
        elif choice_key == "red":
            win = result in [4, 5]
            text = f"Выпало {result} → {'Красный сектор ✅' if win else 'Не красный ❌'}"
        elif choice_key == "white":
            win = result in [2, 3]
            text = f"Выпало {result} → {'Белый сектор ✅' if win else 'Не белый ❌'}"
        elif choice_key == "bounce":
            win = result == 1
            text = f"Выпало {result} → {'Отскок ✅' if win else 'Не отскок ❌'}"
        elif choice_key == "any_sector":
            win = result in [2, 3, 4, 5]
            text = f"Выпало {result} → {'Любой сектор ✅' if win else 'Не сектор ❌'}"
        elif choice_key == "red_or_center":
            win = result in [4, 5, 6]
            text = f"Выпало {result} → {'Красный или Центр ✅' if win else 'НЕ ✅ ❌'}"
        elif choice_key == "white_or_bounce":
            win = result in [1, 2, 3]
            text = f"Выпало {result} → {'Белый или Отскок ✅' if win else 'НЕ ✅ ❌'}"

    elif game_key == "bowling":
        if choice_key == "strike":
            win = result == 6
            text = f"Результат {result} → {'СТРАЙК ✅' if win else 'Не страйк ❌'}"
        elif choice_key == "miss":
            win = result == 1
            text = f"Результат {result} → {'Промах ✅' if win else 'Не промах ❌'}"
        elif choice_key == "p1":
            win = result == 1
            text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p3":
            win = result == 3
            text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p4":
            win = result == 4
            text = f"Сбито {result}/6 → {'✅' if win else '❌'}"
        elif choice_key == "p5":
            win = result == 5
            text = f"Сбито {result}/6 → {'✅' if win else '❌'}"

    elif game_key == "slot":
        if choice_key == "777":
            win = result == 64
            text = f"Выпало {result} → {'ДЖЕКПОТ ✅' if win else 'Не 777 ❌'}"

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
    if data == "custom":
        get_user(cb.from_user.id)["await_dep"] = True
        await cb.message.answer("✏️ Введите сумму (1-10000$):")
        await cb.answer()
        return
    await create_deposit_invoice(cb.message, cb.from_user.id, float(data))
    await cb.answer()


async def create_deposit_invoice(message, uid, amount):
    if crypto is None:
        await message.answer("❌ CryptoPay недоступен")
        return
    try:
        invoice = await crypto.create_invoice(
            asset="USDT", amount=amount,
            description=f"Пополнение",
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
            get_user(uid)["balance"] += amount
            await cb.message.answer(
                f"✅ <b>Баланс пополнен!</b>\n➕ +{amount}$\n💰 Баланс: {get_user(uid)['balance']}$",
                parse_mode="HTML"
            )
            referrer_id = get_user(uid).get("ref")
            if referrer_id:
                bonus = round(amount * REF_PERCENT, 2)
                ref_user = get_user(referrer_id)
                ref_user["balance"] = round(ref_user["balance"] + bonus, 2)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"💸 <b>Реферальный бонус!</b>\n\n"
                        f"👤 Реферал пополнил на <b>{amount}$</b>\n"
                        f"➕ Вам: <b>+{bonus}$</b> (10%)\n"
                        f"💰 Баланс: <b>{ref_user['balance']}$</b>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            try:
                await bot.send_message(ADMIN_ID, f"💳 Пополнение: {get_user(uid).get('username', '?')} — {amount}$")
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
    u = get_user(cb.from_user.id)
    if u["balance"] < WITHDRAW_MIN:
        await cb.message.answer(
            f"❌ <b>Минимум для вывода: {WITHDRAW_MIN}$</b>\n💰 Баланс: <b>{u['balance']}$</b>",
            parse_mode="HTML"
        )
        await cb.answer()
        return
    u["await_withdraw"] = True
    await cb.message.answer(
        f"📤 <b>Вывод средств</b>\n\n"
        f"💰 Баланс: <b>{u['balance']}$</b>\n"
        f"Мин: <b>{WITHDRAW_MIN}$</b>\nМакс: <b>{u['balance']}$</b>\n\n"
        f"✏️ Введите сумму для вывода:",
        parse_mode="HTML"
    )
    await cb.answer()


# ==================== PROFILE / REF ====================
@dp.callback_query(F.data == "profile")
async def cb_profile(cb: types.CallbackQuery):
    uid = cb.from_user.id
    username = f"@{cb.from_user.username}" if cb.from_user.username else cb.from_user.first_name
    u = get_user(uid, username)
    await cb.message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"📛 Имя: <b>{u['username']}</b>\n"
        f"💰 Баланс: <b>{u['balance']}$</b>\n"
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
        f"👥 <b>Пригласите друга и получайте 10% с каждого его пополнения!</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👥 Ваших рефералов: <b>{u['refs']}</b>",
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

    if u.get("pending_game"):
        pg = u["pending_game"]
        game_key, choice_key = pg["game_key"], pg["choice_key"]
        if val < BET_MIN:
            await m.answer(f"❌ Минимальная ставка: {BET_MIN}$")
            return
        if val > BET_MAX:
            await m.answer(f"❌ Максимальная ставка: {BET_MAX}$")
            return
        if val > u["balance"]:
            await m.answer(
                f"❌ <b>Недостаточно средств!</b>\n\nНужно: <b>{val}$</b>\nУ вас: <b>{u['balance']}$</b>",
                parse_mode="HTML"
            )
            return
        u["pending_game"] = None
        await play_game(m, uid, game_key, choice_key, val)
        return

    if u.get("await_dep"):
        if val < 1:
            await m.answer("❌ Мин: 1$")
            return
        if val > 10000:
            await m.answer("❌ Макс: 10000$")
            return
        u["await_dep"] = False
        await create_deposit_invoice(m, uid, val)
        return

    if u.get("await_withdraw"):
        u["await_withdraw"] = False
        if val < WITHDRAW_MIN:
            await m.answer(f"❌ Минимум: {WITHDRAW_MIN}$")
            return
        if val > u["balance"]:
            await m.answer(
                f"❌ Недостаточно средств!\n\nЗапрошено: <b>{val}$</b>\nБаланс: <b>{u['balance']}$</b>",
                parse_mode="HTML"
            )
            return
        if crypto is None:
            await m.answer("❌ CryptoPay недоступен")
            return
        await m.answer("⏳ Создаём чек...")
        try:
            check = await crypto.create_check(
                asset="USDT", amount=round(val, 2), pin_to_user_id=uid
            )
            u["balance"] = round(u["balance"] - val, 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💵 Получить чек", url=check.bot_check_url)],
            ])
            await m.answer(
                f"✅ <b>Чек на вывод создан!</b>\n\n"
                f"💰 Сумма: <b>{val}$</b>\n"
                f"💵 Баланс: <b>{u['balance']}$</b>\n\n"
                f"🎁 Активируйте чек 👇",
                reply_markup=kb, parse_mode="HTML"
            )
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"📤 <b>Вывод</b>\n\n👤 {username}\n💰 Сумма: {val}$\n🔗 {check.bot_check_url}",
                    parse_mode="HTML"
                )
            except:
                pass
        except Exception as e:
            await m.answer(f"❌ <b>Ошибка вывода:</b>\n<code>{e}</code>", parse_mode="HTML")
        return


# ==================== MAIN ====================
async def main():
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
