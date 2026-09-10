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
BOT_TOKEN =
CRYPTO_TOKEN =
ADMIN_ID =
CHAT_LINK =

# ==================== СТАВКА ШЕКТЕУЛЕРІ ====================
BET_MIN = 0.1
BET_MAX = 10000.0
BET_DEFAULT = 0.1
BET_STEP = 0.5
WITHDRAW_MIN = 1.0
REF_PERCENT = 0.10   # 10% реферал бонусы

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

# ==================== ОЙЫНДАР ====================
GAMES = {
    "dice": {
        "emoji": "🎲", "name": "Кости", "choices": {
            "more3": {"name": "Больше (4-6)", "x": 2},
            "less3": {"name": "Меньше (1-2)", "x": 3},
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
        "emoji": "🎯", "name": "Сектор", "choices": {
            "red":    {"name": "Красный сектор", "x": 2},
            "white":  {"name": "Белый сектор", "x": 2},
            "center": {"name": "Прямо в центр", "x": 5},
            "bounce": {"name": "Отскок", "x": 3},
        }
    },
    "bowling": {
        "emoji": "🎳", "name": "Боулинг", "choices": {
            "strike": {"name": "Страйк", "x": 2},
            "miss":   {"name": "Промах", "x": 3},
            "some":   {"name": "Часть сбита", "x": 2},
        }
    },
    "slot": {
        "emoji": "🎰", "name": "777", "choices": {
            "777": {"name": "777 (Джекпот)", "x": 10},
            "any": {"name": "Любая комбинация", "x": 2},
        }
    },
}


def get_user(uid):
    if uid not in users:
        users[uid] = {
            "balance": 0.0,
            "bet": BET_DEFAULT,
            "ref": None,
            "refs": 0,
            "await_bet": False,
            "await_dep": False,
            "await_withdraw": False,
        }
    return users[uid]


def bottom_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="🎮 Играть")],
            [KeyboardButton(text="☰ Меню")],
        ],
        resize_keyboard=True
    )


def main_menu(uid):
    u = get_user(uid)
    bet = u["bet"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
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
            InlineKeyboardButton(text="➖", callback_data="bet_down"),
            InlineKeyboardButton(text=f"💵 Ставка: {bet}$", callback_data="bet_set"),
            InlineKeyboardButton(text="➕", callback_data="bet_up"),
        ],
        [
            InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit"),
            InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw"),
        ],
    ])
    return kb


def menu_text(uid):
    u = get_user(uid)
    return (
        f"🎮 <b>Выберите игру, на которую хотите сделать ставку!</b>\n\n"
        f"➕ Ставка: <b>{u['bet']}$</b>\n"
        f"💵 Баланс: <b>{u['balance']}$</b>"
    )


def game_menu(uid, game_key):
    g = GAMES[game_key]
    buttons = []
    for choice_key, choice in g["choices"].items():
        buttons.append([InlineKeyboardButton(
            text=f"{choice['name']} — x{choice['x']}",
            callback_data=f"bet_{game_key}_{choice_key}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== START ====================
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    uid = m.from_user.id
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            ref_id = int(args[1].replace("ref", ""))
            if ref_id != uid:
                u = get_user(uid)
                if u["ref"] is None:
                    u["ref"] = ref_id
                    get_user(ref_id)["refs"] += 1
                    try:
                        await bot.send_message(
                            ref_id,
                            "🎉 <b>Новый реферал!</b>\n\n"
                            "Теперь вы получаете <b>10%</b> "
                            "с каждого его пополнения!",
                            parse_mode="HTML"
                        )
                    except:
                        pass
        except:
            pass
    u = get_user(uid)
    if u["balance"] == 0.0:
        u["balance"] = 100.0
    await m.answer(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")
    await m.answer("Меню 👇", reply_markup=bottom_menu())


# ==================== REPLY BUTTONS ====================
@dp.message(F.text == "💰 Баланс")
async def btn_balance(m: types.Message):
    u = get_user(m.from_user.id)
    await m.answer(
        f"💰 <b>Ваш баланс:</b> {u['balance']}$\n👥 Рефералов: {u['refs']}",
        parse_mode="HTML"
    )


@dp.message(F.text == "🎮 Играть")
async def btn_play(m: types.Message):
    uid = m.from_user.id
    await m.answer(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")


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
    uid = cb.from_user.id
    await cb.message.edit_text(menu_text(uid), reply_markup=main_menu(uid), parse_mode="HTML")
    await cb.answer()


# ==================== PLAY ====================
@dp.callback_query(F.data.startswith("bet_"))
async def cb_play(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.answer("Ошибка!")
        return
    game_key = parts[1]
    choice_key = parts[2]
    if game_key not in GAMES:
        await cb.answer("Ошибка!")
        return
    g = GAMES[game_key]
    if choice_key not in g["choices"]:
        await cb.answer("Ошибка!")
        return
    choice = g["choices"][choice_key]
    uid = cb.from_user.id
    u = get_user(uid)
    bet = u["bet"]
    if u["balance"] < bet:
        await cb.message.answer(
            f"❌ <b>Недостаточно средств!</b>\n\nНужно: {bet}$\nУ вас: {u['balance']}$",
            parse_mode="HTML"
        )
        await cb.answer()
        return
    await cb.answer()
    dice_msg = await cb.message.answer_dice(emoji=g["emoji"])
    await asyncio.sleep(4)
    result = dice_msg.dice.value
    is_win, result_text = check_win(game_key, choice_key, result)
    if is_win:
        win = round(bet * choice["x"], 2)
        u["balance"] = round(u["balance"] - bet + win, 2)
        text = (
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"{g['emoji']} {g['name']} — {choice['name']}\n"
            f"Результат: <b>{result}</b>\n"
            f"<i>{result_text}</i>\n"
            f"➕ Выигрыш: <b>+{win}$</b>\n"
            f"💰 Баланс: <b>{u['balance']}$</b>"
        )
    else:
        u["balance"] = round(u["balance"] - bet, 2)
        text = (
            f"😢 <b>ПРОИГРЫШ</b>\n\n"
            f"{g['emoji']} {g['name']} — {choice['name']}\n"
            f"Результат: <b>{result}</b>\n"
            f"<i>{result_text}</i>\n"
            f"➖ Проигрыш: <b>-{bet}$</b>\n"
            f"💰 Баланс: <b>{u['balance']}$</b>"
        )
    await cb.message.answer(text, parse_mode="HTML", reply_markup=main_menu(uid))


def check_win(game_key, choice_key, result):
    text = ""
    win = False

    if game_key == "dice":
        if choice_key == "more3":
            win = result >= 4
            text = f"{result} {'больше' if win else 'не больше'} 3"
        elif choice_key == "less3":
            win = result <= 2
            text = f"{result} {'меньше' if win else 'не меньше'} 3"
        elif choice_key == "even":
            win = result % 2 == 0
            text = f"{result} — {'чётное' if win else 'нечётное'}"
        elif choice_key == "odd":
            win = result % 2 == 1
            text = f"{result} — {'нечётное' if win else 'чётное'}"

    elif game_key == "football":
        is_goal = result >= 4
        if choice_key == "goal":
            win = is_goal
            text = "⚽ Гол!" if is_goal else "Промах"
        elif choice_key == "miss":
            win = not is_goal
            text = "Промах" if not is_goal else "⚽ Гол!"

    elif game_key == "basketball":
        is_goal = result >= 4
        if choice_key == "goal":
            win = is_goal
            text = "🏀 Гол!" if is_goal else "Промах"
        elif choice_key == "miss":
            win = not is_goal
            text = "Промах" if not is_goal else "🏀 Гол!"

    elif game_key == "darts":
        if choice_key == "center":
            win = result == 6
            text = "🎯 В центр!" if win else f"Не в центр ({result})"
        elif choice_key == "red":
            win = result == 5
            text = "🔴 Красный!" if win else f"Не красный ({result})"
        elif choice_key == "white":
            win = result in [3, 4]
            text = "⚪ Белый!" if win else f"Не белый ({result})"
        elif choice_key == "bounce":
            win = result in [1, 2]
            text = "↩️ Отскок" if win else f"Не отскок ({result})"

    elif game_key == "bowling":
        if choice_key == "strike":
            win = result == 6
            text = "🎳 Страйк!" if win else f"Не страйк ({result})"
        elif choice_key == "miss":
            win = result <= 1
            text = "❌ Промах" if win else f"Сбито {result}"
        elif choice_key == "some":
            win = 2 <= result <= 5
            text = f"Сбито {result}" if win else f"Не часть ({result})"

    elif game_key == "slot":
        if choice_key == "777":
            win = result == 64
            text = "🎰 ДЖЕКПОТ 777!" if win else f"Не 777 ({result})"
        elif choice_key == "any":
            win = result >= 1
            text = f"Выпало {result}"

    return win, text


# ==================== BET ====================
@dp.callback_query(F.data == "bet_up")
async def bet_up(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    u["bet"] = min(round(u["bet"] + BET_STEP, 2), BET_MAX)
    await cb.message.edit_text(menu_text(cb.from_user.id), reply_markup=main_menu(cb.from_user.id), parse_mode="HTML")
    await cb.answer(f"Ставка: {u['bet']}$")


@dp.callback_query(F.data == "bet_down")
async def bet_down(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    u["bet"] = max(round(u["bet"] - BET_STEP, 2), BET_MIN)
    await cb.message.edit_text(menu_text(cb.from_user.id), reply_markup=main_menu(cb.from_user.id), parse_mode="HTML")
    await cb.answer(f"Ставка: {u['bet']}$")


@dp.callback_query(F.data == "bet_set")
async def bet_set(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    u["await_bet"] = True
    await cb.message.answer(
        f"✏️ <b>Введите сумму ставки</b>\n\nМин: <b>{BET_MIN}$</b>\nМакс: <b>{BET_MAX}$</b>",
        parse_mode="HTML"
    )
    await cb.answer()


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
        u = get_user(cb.from_user.id)
        u["await_dep"] = True
        await cb.message.answer("✏️ Введите сумму (1-10000$):")
        await cb.answer()
        return
    amount = float(data)
    await create_deposit_invoice(cb.message, cb.from_user.id, amount)
    await cb.answer()


async def create_deposit_invoice(message, uid, amount):
    if crypto is None:
        await message.answer("❌ CryptoPay недоступен")
        return
    try:
        invoice = await crypto.create_invoice(
            asset="USDT", amount=amount,
            description=f"Пополнение (ID: {uid})",
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
    invoice_id = int(parts[1])
    amount = float(parts[2])
    uid = cb.from_user.id
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

            # ===== 10% РЕФЕРАЛ БОНУСЫ =====
            referrer_id = get_user(uid).get("ref")
            if referrer_id:
                bonus = round(amount * REF_PERCENT, 2)
                ref_user = get_user(referrer_id)
                ref_user["balance"] = round(ref_user["balance"] + bonus, 2)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"💸 <b>Реферальный бонус!</b>\n\n"
                        f"👤 Ваш реферал пополнил на <b>{amount}$</b>\n"
                        f"➕ Вам начислено: <b>+{bonus}$</b> (10%)\n"
                        f"💰 Ваш баланс: <b>{ref_user['balance']}$</b>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            # =============================

            try:
                await bot.send_message(ADMIN_ID, f"💳 Пополнение: {uid} — {amount}$")
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
            f"❌ <b>Минимум для вывода: {WITHDRAW_MIN}$</b>\n\n💰 Баланс: <b>{u['balance']}$</b>",
            parse_mode="HTML"
        )
        await cb.answer()
        return
    u["await_withdraw"] = True
    await cb.message.answer(
        f"📤 <b>Вывод средств</b>\n\n"
        f"💰 Ваш баланс: <b>{u['balance']}$</b>\n"
        f"Мин: <b>{WITHDRAW_MIN}$</b>\n"
        f"Макс: <b>{u['balance']}$</b>\n\n"
        f"✏️ Введите сумму для вывода:\nНапример: <code>5</code>",
        parse_mode="HTML"
    )
    await cb.answer()


# ==================== PROFILE / REF ====================
@dp.callback_query(F.data == "profile")
async def cb_profile(cb: types.CallbackQuery):
    u = get_user(cb.from_user.id)
    await cb.message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{cb.from_user.id}</code>\n"
        f"💰 Баланс: <b>{u['balance']}$</b>\n"
        f"👥 Рефералов: <b>{u['refs']}</b>\n"
        f"🎯 Ставка: <b>{u['bet']}$</b>",
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
        f"💰 Пример: друг пополнил 10$ → вы получаете <b>+1$</b>\n"
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
async def set_bet_text(m: types.Message):
    uid = m.from_user.id
    u = get_user(uid)
    val = float(m.text)

    # ===== СТАВКА =====
    if u.get("await_bet"):
        if val < BET_MIN:
            await m.answer(f"❌ Мин: {BET_MIN}$")
            return
        if val > BET_MAX:
            await m.answer(f"❌ Макс: {BET_MAX}$")
            return
        u["bet"] = round(val, 2)
        u["await_bet"] = False
        await m.answer(f"✅ <b>Ставка: {u['bet']}$</b>", parse_mode="HTML", reply_markup=main_menu(uid))
        return

    # ===== ПОПОЛНЕНИЕ =====
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

    # ===== ВЫВОД =====
    if u.get("await_withdraw"):
        u["await_withdraw"] = False

        if val < WITHDRAW_MIN:
            await m.answer(f"❌ Минимум: {WITHDRAW_MIN}$")
            return

        if val > u["balance"]:
            await m.answer(
                f"❌ Недостаточно средств!\n\n"
                f"Запрошено: <b>{val}$</b>\n"
                f"Баланс: <b>{u['balance']}$</b>",
                parse_mode="HTML"
            )
            return

        if crypto is None:
            await m.answer("❌ CryptoPay недоступен")
            return

        await m.answer("⏳ Создаём чек...")

        try:
            check = await crypto.create_check(
                asset="USDT",
                amount=round(val, 2),
                pin_to_user_id=uid,
            )
            u["balance"] = round(u["balance"] - val, 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💵 Получить чек", url=check.bot_check_url)],
            ])
            await m.answer(
                f"✅ <b>Чек на вывод создан!</b>\n\n"
                f"💰 Сумма: <b>{val}$</b>\n"
                f"💵 Баланс: <b>{u['balance']}$</b>\n\n"
                f"🎁 Активируйте чек 👇\n"
                f"⚠️ Чек привязан к вашему аккаунту.",
                reply_markup=kb, parse_mode="HTML"
            )
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"📤 <b>Вывод</b>\n\n👤 User: <code>{uid}</code>\n💰 Сумма: {val}$\n🔗 {check.bot_check_url}",
                    parse_mode="HTML"
                )
            except:
                pass
        except Exception as e:
            await m.answer(
                f"❌ <b>Ошибка вывода:</b>\n<code>{e}</code>\n\nНапишите: @admin",
                parse_mode="HTML"
            )
        return


# ==================== MAIN ====================
async def main():
    print("=" * 40)
    print("🤖 Бот запущен!")
    me = await bot.get_me()
    print("Бот:", me.username)
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
