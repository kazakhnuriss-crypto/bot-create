import asyncio
import logging
import os
import sqlite3
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiocryptopay import AioCryptoPay, Networks

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CHAT_LINK = os.getenv("CHAT_LINK", "")
DB_PATH = os.getenv("DB_PATH", "bot.db")

BET_MIN = 0.1
BET_MAX = 10000
WITHDRAW_MIN = 1
REF_PERCENT = 0.10
HOUSE_EDGE = 0.05
DAILY_BONUS = 0.5

# Мина коэффициенттері (3x3 = 9 клеток)
MINES_MULT = {
    1: [1.08, 1.14, 1.21, 1.29, 1.38, 1.48, 1.60, 1.76],  # 8 клеток
    3: [1.65, 1.82, 2.02, 2.26, 2.55, 2.97],                # 6 клеток
    5: [3.00, 3.80, 4.70, 6.00],                            # 4 клетки
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

crypto = None
try:
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)
except Exception as e:
    print(f"CryptoPay: {e}")

mines_state = {}
awaiting = {}

# ==================== DB ====================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
        ref INTEGER, refs INTEGER DEFAULT 0, total_bets REAL DEFAULT 0,
        games_played INTEGER DEFAULT 0, total_won REAL DEFAULT 0,
        total_deposit REAL DEFAULT 0, last_bonus TEXT)""")
    conn.commit(); conn.close()

def db_get(uid, username=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    if not row:
        name = username or f"Player{uid%10000}"
        c.execute("INSERT INTO users(uid,username) VALUES(?,?)", (uid, name))
        conn.commit()
        c.execute("SELECT * FROM users WHERE uid=?", (uid,))
        row = c.fetchone()
    elif username:
        c.execute("UPDATE users SET username=? WHERE uid=?", (username, uid))
        conn.commit()
    conn.close()
    return {"uid": row[0], "username": row[1], "balance": row[2], "ref": row[3],
            "refs": row[4], "total_bets": row[5], "games_played": row[6],
            "total_won": row[7], "total_deposit": row[8], "last_bonus": row[9]} if row else None

def db_upd(uid, **kw):
    if not kw: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    f = ", ".join(f"{k}=?" for k in kw)
    c.execute(f"UPDATE users SET {f} WHERE uid=?", list(kw.values()) + [uid])
    conn.commit(); conn.close()

def fmt(b): return f"{b:.2f}"
def uname(u): return f"@{u.username}" if u.username else u.first_name

# ==================== KEYBOARDS ====================
def kb_main(uid):
    btns = [
        [InlineKeyboardButton(text="🎮 Играть", callback_data="games")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
         InlineKeyboardButton(text="🏆 Топ", callback_data="top")],
        [InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="bonus"),
         InlineKeyboardButton(text="👥 Реферал", callback_data="ref")],
    ]
    if uid == ADMIN_ID:
        btns.append([InlineKeyboardButton(text="👑 АДМИН-ПАНЕЛЬ", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def kb_games():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Мина", callback_data="mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="dice")],
        [InlineKeyboardButton(text="🎳 Боулинг", callback_data="bowling"),
         InlineKeyboardButton(text="🎯 Дартс", callback_data="darts")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
    ])

def kb_mines_lvl():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 1 мина (x1.08-1.76)", callback_data="mines_l_1")],
        [InlineKeyboardButton(text="🟡 3 мины (x1.65-2.97)", callback_data="mines_l_3")],
        [InlineKeyboardButton(text="🔴 5 мин (x3.00-6.00)", callback_data="mines_l_5")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="games")],
    ])

def kb_mines_field(game, show_mines=False):
    rows = []
    for i in range(3):
        r = []
        for j in range(3):
            p = i*3 + j
            if p in game.get("opened", []):
                t = "💎"
            elif show_mines and p in game["mines"]:
                t = "💣"
            else:
                t = "⬜"
            cb = f"mines_o_{p}" if not show_mines and p not in game.get("opened", []) else "noop"
            r.append(InlineKeyboardButton(text=t, callback_data=cb))
        rows.append(r)
    if not show_mines and game.get("opened"):
        rows.append([InlineKeyboardButton(text=f"💰 Забрать x{game['mult']:.2f}", callback_data="mines_cash")])
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="mines_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_dice():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Больше (4-6) x2", callback_data="dice_more3"),
         InlineKeyboardButton(text="Меньше (1-3) x2", callback_data="dice_less3")],
        [InlineKeyboardButton(text="Чётное (2,4,6) x2", callback_data="dice_even"),
         InlineKeyboardButton(text="Нечётное (1,3,5) x2", callback_data="dice_odd")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="games")],
    ])

def kb_bowl():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Промах x3", callback_data="bowl_miss"),
         InlineKeyboardButton(text="🎳 Страйк x3", callback_data="bowl_strike")],
        [InlineKeyboardButton(text="🎯 Угадать часть сбитых x5", callback_data="bowl_portion")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="games")],
    ])

def kb_bowl_portion():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1/6", callback_data="bowl_p_1"),
         InlineKeyboardButton(text="2/6", callback_data="bowl_p_2"),
         InlineKeyboardButton(text="3/6", callback_data="bowl_p_3")],
        [InlineKeyboardButton(text="4/6", callback_data="bowl_p_4"),
         InlineKeyboardButton(text="5/6", callback_data="bowl_p_5")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="bowling")],
    ])

def kb_darts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красный x2", callback_data="darts_red"),
         InlineKeyboardButton(text="⚪ Белый x2", callback_data="darts_white")],
        [InlineKeyboardButton(text="🎯 Центр x5", callback_data="darts_center"),
         InlineKeyboardButton(text="↩️ Отскок x3", callback_data="darts_bounce")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="games")],
    ])

def kb_top():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 По балансу", callback_data="top_bal")],
        [InlineKeyboardButton(text="🎮 По играм", callback_data="top_g")],
        [InlineKeyboardButton(text="👥 По рефералам", callback_data="top_r")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
    ])

def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="ad_stats")],
        [InlineKeyboardButton(text="👥 Все игроки", callback_data="ad_users")],
        [InlineKeyboardButton(text="💬 Как выдать бонус", callback_data="ad_bonus_help")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
    ])

def kb_dep():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1$", callback_data="dep_1"),
         InlineKeyboardButton(text="5$", callback_data="dep_5"),
         InlineKeyboardButton(text="10$", callback_data="dep_10")],
        [InlineKeyboardButton(text="25$", callback_data="dep_25"),
         InlineKeyboardButton(text="50$", callback_data="dep_50"),
         InlineKeyboardButton(text="✏️ Своя", callback_data="dep_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")],
    ])

def kb_back(target="main"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]])

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
        f"🎰 <b>STAVKA BOT</b>\n\n"
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"💰 Баланс: <b>{fmt(u['balance'])}$</b>\n"
        f"👥 Рефералов: <b>{u['refs']}</b>",
        reply_markup=kb_main(uid), parse_mode="HTML"
    )

@dp.callback_query(F.data == "main")
async def cb_main(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid, uname(cb.from_user))
    try:
        await cb.message.edit_text(
            f"🎰 <b>STAVKA BOT</b>\n\n"
            f"💰 Баланс: <b>{fmt(u['balance'])}$</b>\n"
            f"👥 Рефералов: <b>{u['refs']}</b>",
            reply_markup=kb_main(uid), parse_mode="HTML"
        )
    except: pass
    await cb.answer()

@dp.callback_query(F.data == "games")
async def cb_games(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🎮 <b>Выбери игру</b>\n\n"
        "💣 <b>Мина</b> — открывай безопасные клетки\n"
        "🎲 <b>Кости</b> — угадай бросок\n"
        "🎳 <b>Боулинг</b> — сбей кегли\n"
        "🎯 <b>Дартс</b> — попади в цель",
        reply_markup=kb_games(), parse_mode="HTML"
    )
    await cb.answer()

# ==================== BALANCE ====================
@dp.callback_query(F.data == "balance")
async def cb_balance(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid, uname(cb.from_user))
    await cb.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"📛 {u['username']}\n"
        f"💰 Баланс: <b>{fmt(u['balance'])}$</b>\n"
        f"💳 Пополнений: <b>{fmt(u['total_deposit'])}$</b>\n"
        f"🎮 Игр: <b>{u['games_played']}</b>\n"
        f"💸 Ставок: <b>{fmt(u['total_bets'])}$</b>\n"
        f"🏆 Выиграно: <b>{fmt(u['total_won'])}$</b>\n"
        f"👥 Рефералов: <b>{u['refs']}</b>",
        reply_markup=kb_main(uid), parse_mode="HTML"
    )
    await cb.answer()

# ==================== MINES ====================
@dp.callback_query(F.data == "mines")
async def cb_mines(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "💣 <b>МИНА</b>\n\n"
        "Сетка 3×3. Мины спрятаны.\n"
        "Открывай 💎 — коэффициент растёт!\n"
        "Попадёшь на 💣 — потеряешь ставку.\n\n"
        "<b>Выбери сложность:</b>",
        reply_markup=kb_mines_lvl(), parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("mines_l_"))
async def cb_mines_l(cb: types.CallbackQuery):
    uid = cb.from_user.id
    lvl = int(cb.data.replace("mines_l_", ""))
    awaiting[uid] = {"game": "mines", "level": lvl}
    u = db_get(uid)
    await cb.message.answer(
        f"💣 <b>Мина — {lvl} мин</b>\n\n"
        f"💰 Баланс: <b>{fmt(u['balance'])}$</b>\n\n"
        f"✏️ Введи сумму ставки:",
        parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("mines_o_"))
async def cb_mines_open(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_state:
        await cb.answer("Игра не найдена", show_alert=True); return
    g = mines_state[uid]
    pos = int(cb.data.replace("mines_o_", ""))
    if pos in g["opened"]:
        await cb.answer("Уже открыто"); return
    
    if pos in g["mines"]:
        # Проигрыш
        db_upd(uid, balance=g["bal_after"], total_bets=round(db_get(uid)["total_bets"]+g["bet"],2), games_played=db_get(uid)["games_played"]+1)
        g["opened"].append(pos)
        del mines_state[uid]
        try:
            await cb.message.edit_text(
                f"💥 <b>БУМ!</b>\n\n"
                f"💣 Ты наткнулся на мину!\n"
                f"💸 Потеряно: <b>-{fmt(g['bet'])}$</b>\n"
                f"💰 Баланс: <b>{fmt(g['bal_after'])}$</b>",
                reply_markup=kb_mines_field(g, show_mines=True), parse_mode="HTML"
            )
            # Добавим кнопки снизу
            rows = []
            for i in range(3):
                r = []
                for j in range(3):
                    p = i*3+j
                    if p in g["mines"]: t = "💣"
                    elif p in g["opened"]: t = "💎"
                    else: t = "⬜"
                    r.append(InlineKeyboardButton(text=t, callback_data="noop"))
                rows.append(r)
            rows.append([InlineKeyboardButton(text="🔄 Снова", callback_data="mines")])
            rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="main")])
            await cb.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except: pass
        await cb.answer("💥 Мина!", show_alert=True); return
    
    # Безопасно
    g["opened"].append(pos)
    idx = len(g["opened"]) - 1
    mults = MINES_MULT[g["level"]]
    if idx < len(mults):
        g["mult"] = mults[idx]
    
    safe_total = 9 - g["level"]
    if len(g["opened"]) >= safe_total:
        # Все клетки открыты — авто-выигрыш
        win_full = g["bet"] * g["mult"]
        comm = win_full * HOUSE_EDGE
        profit = round(win_full - comm, 2)
        new_bal = round(g["bal_after"] + profit, 2)
        u = db_get(uid)
        db_upd(uid, balance=new_bal, total_bets=round(u["total_bets"]+g["bet"],2),
               games_played=u["games_played"]+1, total_won=round(u["total_won"]+profit,2))
        del mines_state[uid]
        rows = []
        for i in range(3):
            r = [InlineKeyboardButton(text="💎", callback_data="noop") for _ in range(3)]
            rows.append(r)
        rows.append([InlineKeyboardButton(text="🔄 Снова", callback_data="mines")])
        rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="main")])
        try:
            await cb.message.edit_text(
                f"🎉 <b>ПОБЕДА!</b>\n\n"
                f"Открыл все безопасные!\n"
                f"🎯 x{g['mult']:.2f}\n"
                f"➕ Выигрыш: <b>+{fmt(profit)}$</b>\n"
                f"💰 Баланс: <b>{fmt(new_bal)}$</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML"
            )
        except: pass
        await cb.answer("🎉 Победа!"); return
    
    try: await cb.message.edit_reply_markup(reply_markup=kb_mines_field(g))
    except: pass
    await cb.answer(f"💎 x{g['mult']:.2f}")

@dp.callback_query(F.data == "mines_cash")
async def cb_mines_cash(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_state:
        await cb.answer("Игра не найдена", show_alert=True); return
    g = mines_state[uid]
    if not g["opened"]:
        await cb.answer("Открой хотя бы 1 клетку!", show_alert=True); return
    win_full = g["bet"] * g["mult"]
    comm = win_full * HOUSE_EDGE
    profit = round(win_full - comm, 2)
    new_bal = round(g["bal_after"] + profit, 2)
    u = db_get(uid)
    db_upd(uid, balance=new_bal, total_bets=round(u["total_bets"]+g["bet"],2),
           games_played=u["games_played"]+1, total_won=round(u["total_won"]+profit,2))
    # Show full field
    rows = []
    for i in range(3):
        r = []
        for j in range(3):
            p = i*3+j
            if p in g["mines"]: t = "💣"
            elif p in g["opened"]: t = "💎"
            else: t = "⬜"
            r.append(InlineKeyboardButton(text=t, callback_data="noop"))
        rows.append(r)
    rows.append([InlineKeyboardButton(text="🔄 Снова", callback_data="mines")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="main")])
    del mines_state[uid]
    try:
        await cb.message.edit_text(
            f"💰 <b>Забрал выигрыш!</b>\n\n"
            f"🎯 x{g['mult']:.2f}\n"
            f"💵 +{fmt(profit)}$\n"
            f"💰 Баланс: <b>{fmt(new_bal)}$</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML"
        )
    except: pass
    await cb.answer(f"💰 +{fmt(profit)}$")

@dp.callback_query(F.data == "mines_cancel")
async def cb_mines_cancel(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if uid in mines_state:
        g = mines_state[uid]
        db_upd(uid, balance=g["bal_after"])
        del mines_state[uid]
    try: await cb.message.edit_text("❌ Игра отменена.", reply_markup=kb_main(uid))
    except: pass
    await cb.answer()

# ==================== DICE ====================
@dp.callback_query(F.data == "dice")
async def cb_dice(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🎲 <b>КОСТИ</b>\n\nУгадай результат броска!",
        reply_markup=kb_dice(), parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("dice_"))
async def cb_dice_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    bt = cb.data.replace("dice_", "")
    awaiting[uid] = {"game": "dice", "bet": bt}
    u = db_get(uid)
    await cb.message.answer(
        f"🎲 <b>Кости</b>\n\n💰 Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:",
        parse_mode="HTML"
    )
    await cb.answer()

# ==================== BOWLING ====================
@dp.callback_query(F.data == "bowling")
async def cb_bowl(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🎳 <b>БОУЛИНГ</b>\n\nВыбери тип ставки:",
        reply_markup=kb_bowl(), parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("bowl_"))
async def cb_bowl_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    data = cb.data.replace("bowl_", "")
    if data == "portion":
        await cb.message.edit_text(
            "🎯 <b>Угадай часть сбитых</b> (x5)\n\nСколько кеглей?",
            reply_markup=kb_bowl_portion(), parse_mode="HTML"
        )
        await cb.answer(); return
    if data.startswith("p_"):
        n = int(data.replace("p_", ""))
        awaiting[uid] = {"game": "bowl", "bet": f"p_{n}"}
    else:
        awaiting[uid] = {"game": "bowl", "bet": data}
    u = db_get(uid)
    await cb.message.answer(
        f"🎳 <b>Боулинг</b>\n\n💰 Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:",
        parse_mode="HTML"
    )
    await cb.answer()

# ==================== DARTS ====================
@dp.callback_query(F.data == "darts")
async def cb_darts(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🎯 <b>ДАРТС</b>\n\n"
        "🔴 Красный — x2\n"
        "⚪ Белый — x2\n"
        "🎯 Центр — x5\n"
        "↩️ Отскок — x3",
        reply_markup=kb_darts(), parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("darts_"))
async def cb_darts_bet(cb: types.CallbackQuery):
    uid = cb.from_user.id
    bt = cb.data.replace("darts_", "")
    awaiting[uid] = {"game": "darts", "bet": bt}
    u = db_get(uid)
    await cb.message.answer(
        f"🎯 <b>Дартс</b>\n\n💰 Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:",
        parse_mode="HTML"
    )
    await cb.answer()

# ==================== BET INPUT ====================
@dp.message(F.text.regexp(r"^\d+(\.\d+)?$"))
async def msg_num(m: types.Message):
    uid = m.from_user.id
    name = uname(m.from_user)
    u = db_get(uid, name)
    val = float(m.text)
    
    if uid in awaiting and awaiting[uid].get("dep_custom"):
        awaiting.pop(uid)
        if val < 1 or val > 10000: await m.answer("❌ 1-10000$"); return
        await do_deposit(m, uid, val); return
    
    if uid in awaiting and awaiting[uid].get("withdraw"):
        awaiting.pop(uid)
        if val < WITHDRAW_MIN: await m.answer(f"❌ Мин: {WITHDRAW_MIN}$"); return
        if val > u["balance"]: await m.answer("❌ Недостаточно"); return
        await do_withdraw(m, uid, val); return
    
    if uid not in awaiting or "game" not in awaiting[uid]:
        return
    
    t = awaiting[uid]
    g = t["game"]
    if val < BET_MIN: await m.answer(f"❌ Мин: {BET_MIN}$"); return
    if val > BET_MAX: await m.answer(f"❌ Макс: {BET_MAX}$"); return
    if val > u["balance"]: await m.answer(f"❌ Недостаточно. Баланс: {fmt(u['balance'])}$"); return
    
    new_bal = round(u["balance"] - val, 2)
    db_upd(uid, balance=new_bal)
    
    # === MINES ===
    if g == "mines":
        lvl = t["level"]
        mines = random.sample(range(9), lvl)
        mines_state[uid] = {"bet": val, "level": lvl, "mines": mines,
                            "opened": [], "mult": 0, "bal_after": new_bal}
        awaiting.pop(uid)
        await m.answer(
            f"💣 <b>Мина — {lvl} мин</b>\n\n💵 Ставка: <b>{fmt(val)}$</b>\n\nОткрывай клетки! 💎",
            reply_markup=kb_mines_field(mines_state[uid]), parse_mode="HTML"
        )
        return
    
    # === DICE ===
    if g == "dice":
        bt = t["bet"]
        awaiting.pop(uid)
        dm = await m.answer_dice(emoji="🎲")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False
        if bt == "more3" and r >= 4: win = True
        elif bt == "less3" and r <= 3: win = True
        elif bt == "even" and r in [2,4,6]: win = True
        elif bt == "odd" and r in [1,3,5]: win = True
        await end_game(m, uid, val, win, 2, f"🎲 Выпало {r}", "dice")
        return
    
    # === BOWLING ===
    if g == "bowl":
        bt = t["bet"]
        awaiting.pop(uid)
        dm = await m.answer_dice(emoji="🎳")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False; mult = 3
        if bt == "miss":
            win = (r == 1)
            txt = f"🎳 {r}/6 → " + ("Промах ✅" if win else "Не промах ❌")
        elif bt == "strike":
            win = (r == 6)
            txt = f"🎳 {r}/6 → " + ("Страйк ✅" if win else "Не страйк ❌")
        elif bt.startswith("p_"):
            n = int(bt.replace("p_", ""))
            win = (r == n); mult = 5
            txt = f"🎳 {r}/6 → " + (f"Угадал {n}/6 ✅" if win else f"Не угадал ❌")
        await end_game(m, uid, val, win, mult, txt, "bowling")
        return
    
    # === DARTS ===
    if g == "darts":
        bt = t["bet"]
        awaiting.pop(uid)
        dm = await m.answer_dice(emoji="🎯")
        await asyncio.sleep(4)
        r = dm.dice.value
        win = False; mult = 2
        if bt == "red":
            win = r in [2, 4]
            txt = f"🎯 {r} → " + ("🔴 Красный ✅" if win else "Не красный ❌")
        elif bt == "white":
            win = r in [3, 5]
            txt = f"🎯 {r} → " + ("⚪ Белый ✅" if win else "Не белый ❌")
        elif bt == "center":
            win = r == 6; mult = 5
            txt = f"🎯 {r} → " + ("🎯 Центр ✅" if win else "Не центр ❌")
        elif bt == "bounce":
            win = r == 1; mult = 3
            txt = f"🎯 {r} → " + ("↩️ Отскок ✅" if win else "Не отскок ❌")
        await end_game(m, uid, val, win, mult, txt, "darts")
        return

async def end_game(msg, uid, bet, win, mult, text_res, game_code):
    u = db_get(uid)
    if win:
        wf = round(bet * mult, 2)
        comm = round(wf * HOUSE_EDGE, 2)
        profit = round(wf - comm, 2)
        nb = round(u["balance"] + profit, 2)
        db_upd(uid, balance=nb, total_bets=round(u["total_bets"]+bet,2),
               games_played=u["games_played"]+1, total_won=round(u["total_won"]+profit,2))
        text = (f"🎉 <b>ПОБЕДА!</b>\n\n📊 {text_res}\n\n"
                f"💵 Ставка: {fmt(bet)}$\n🎯 x{mult}\n"
                f"➕ Выигрыш: <b>+{fmt(profit)}$</b>\n💰 Баланс: <b>{fmt(nb)}$</b>")
    else:
        db_upd(uid, total_bets=round(u["total_bets"]+bet,2), games_played=u["games_played"]+1)
        text = (f"😢 <b>ПРОИГРЫШ</b>\n\n📊 {text_res}\n\n"
                f"💸 Потеряно: <b>-{fmt(bet)}$</b>\n💰 Баланс: <b>{fmt(u['balance'])}$</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Снова", callback_data=game_code)],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="main")],
    ])
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")

# ==================== DEPOSIT ====================
@dp.callback_query(F.data == "deposit")
async def cb_dep(cb: types.CallbackQuery):
    await cb.message.edit_text("💳 <b>Пополнение</b>\n\nВыбери сумму:", reply_markup=kb_dep(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("dep_"))
async def cb_dep_amt(cb: types.CallbackQuery):
    d = cb.data.replace("dep_", "")
    uid = cb.from_user.id
    if d == "custom":
        awaiting[uid] = {"dep_custom": True}
        await cb.message.answer("✏️ Введи сумму (1-10000$):")
        await cb.answer(); return
    await do_deposit(cb.message, uid, float(d))
    await cb.answer()

async def do_deposit(msg, uid, amount):
    if not crypto:
        await msg.answer("❌ CryptoBot недоступен"); return
    try:
        inv = await crypto.create_invoice(asset="USDT", amount=amount,
            description=f"Deposit #{uid}", payload=f"dep_{uid}_{amount}", expires_in=1800)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=inv.bot_invoice_url)],
            [InlineKeyboardButton(text="✅ Проверить", callback_data=f"chk_{inv.invoice_id}_{amount}")],
        ])
        await msg.answer(f"💳 <b>Счёт {amount}$</b>\n\nОплати 👇", reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await msg.answer(f"❌ {e}")

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
            await cb.message.answer(f"✅ <b>+{amount}$</b>\n💰 Баланс: <b>{fmt(nb)}$</b>", parse_mode="HTML")
            if u["ref"]:
                bonus = round(amount * REF_PERCENT, 2)
                ru = db_get(u["ref"])
                db_upd(u["ref"], balance=round(ru["balance"]+bonus,2))
                try: await bot.send_message(u["ref"], f"💸 +{bonus}$ реф. бонус")
                except: pass
        else:
            await cb.message.answer("⏳ Ещё не оплачено")
    except Exception as e:
        await cb.message.answer(f"❌ {e}")
    await cb.answer()

# ==================== WITHDRAW ====================
@dp.callback_query(F.data == "withdraw")
async def cb_wd(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid)
    if u["balance"] < WITHDRAW_MIN:
        await cb.answer(f"Мин: {WITHDRAW_MIN}$", show_alert=True); return
    awaiting[uid] = {"withdraw": True}
    await cb.message.answer(
        f"📤 <b>Вывод</b>\n\n💰 Баланс: <b>{fmt(u['balance'])}$</b>\n\n✏️ Введи сумму:",
        parse_mode="HTML"
    )
    await cb.answer()

async def do_withdraw(msg, uid, amount):
    u = db_get(uid)
    try:
        chk = await crypto.create_check(asset="USDT", amount=round(amount,2), pin_to_user_id=uid)
        db_upd(uid, balance=round(u["balance"]-amount,2))
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💵 Получить", url=chk.bot_check_url)]])
        await msg.answer(f"✅ <b>Чек {amount}$</b>\n\nАктивируй 👇", reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await msg.answer("❌ <b>Вывод временно не работает</b>\n\nПопробуйте позже.", parse_mode="HTML")

# ==================== BONUS ====================
@dp.callback_query(F.data == "bonus")
async def cb_bonus(cb: types.CallbackQuery):
    uid = cb.from_user.id
    u = db_get(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    if u["last_bonus"] == today:
        await cb.answer("🎁 Уже получил сегодня!", show_alert=True); return
    nb = round(u["balance"] + DAILY_BONUS, 2)
    db_upd(uid, balance=nb, last_bonus=today)
    await cb.message.answer(f"🎁 <b>+{DAILY_BONUS}$</b>\n💰 Баланс: <b>{fmt(nb)}$</b>", parse_mode="HTML")
    await cb.answer("🎁 Бонус!")

# ==================== REFERRAL ====================
@dp.callback_query(F.data == "ref")
async def cb_ref(cb: types.CallbackQuery):
    uid = cb.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{uid}"
    u = db_get(uid)
    await cb.message.edit_text(
        f"👥 <b>Рефералы</b>\n\n"
        f"Приглашай — получай <b>10%</b> с пополнений!\n\n"
        f"🔗 <code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{u['refs']}</b>",
        reply_markup=kb_main(uid), parse_mode="HTML"
    )
    await cb.answer()

# ==================== TOP ====================
@dp.callback_query(F.data == "top")
async def cb_top(cb: types.CallbackQuery):
    await cb.message.edit_text("🏆 <b>Топы</b>", reply_markup=kb_top(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("top_"))
async def cb_top_show(cb: types.CallbackQuery):
    t = cb.data.replace("top_", "")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    medals = ["🥇", "🥈", "🥉"]
    if t == "bal":
        c.execute("SELECT username, balance FROM users WHERE balance>0 ORDER BY balance DESC LIMIT 10")
        rows = c.fetchall()
        text = "💰 <b>ТОП ПО БАЛАНСУ</b>\n\n"
        for i,(n,b) in enumerate(rows,1):
            m = medals[i-1] if i<=3 else f"<b>{i}.</b>"
            text += f"{m} {n} — <b>{fmt(b)}$</b>\n"
    elif t == "g":
        c.execute("SELECT username, games_played FROM users WHERE games_played>0 ORDER BY games_played DESC LIMIT 10")
        rows = c.fetchall()
        text = "🎮 <b>ТОП ИГРОКОВ</b>\n\n"
        for i,(n,g) in enumerate(rows,1):
            m = medals[i-1] if i<=3 else f"<b>{i}.</b>"
            text += f"{m} {n} — <b>{g}</b> игр\n"
    else:
        c.execute("SELECT username, refs FROM users WHERE refs>0 ORDER BY refs DESC LIMIT 10")
        rows = c.fetchall()
        text = "👥 <b>ТОП РЕФЕРАЛОВ</b>\n\n"
        for i,(n,r) in enumerate(rows,1):
            m = medals[i-1] if i<=3 else f"<b>{i}.</b>"
            text += f"{m} {n} — <b>{r}</b> реф.\n"
    conn.close()
    if not rows: text += "Пока никого нет"
    await cb.message.edit_text(text, reply_markup=kb_top(), parse_mode="HTML")
    await cb.answer()

# ==================== ADMIN ====================
@dp.callback_query(F.data == "admin")
async def cb_adm(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: await cb.answer("Нет доступа", show_alert=True); return
    await cb.message.edit_text("👑 <b>АДМИН-ПАНЕЛЬ</b>", reply_markup=kb_admin(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "ad_stats")
async def cb_ad_stats(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(balance), SUM(total_bets), SUM(games_played), SUM(total_deposit), SUM(refs) FROM users")
    r = c.fetchone()
    conn.close()
    await cb.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Игроков: <b>{r[0] or 0}</b>\n"
        f"💰 Общий баланс: <b>{fmt(r[1] or 0)}$</b>\n"
        f"💵 Всего ставок: <b>{fmt(r[2] or 0)}$</b>\n"
        f"🎮 Игр: <b>{r[3] or 0}</b>\n"
        f"💳 Пополнений: <b>{fmt(r[4] or 0)}$</b>\n"
        f"👥 Рефералов: <b>{r[5] or 0}</b>",
        reply_markup=kb_admin(), parse_mode="HTML"
    )
    await cb.answer()

@dp.callback_query(F.data == "ad_users")
async def cb_ad_users(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, balance, refs FROM users ORDER BY balance DESC LIMIT 30")
    rows = c.fetchall()
    conn.close()
    text = "👥 <b>Все игроки</b>\n\n"
    for i,(n,b,r) in enumerate(rows,1):
        text += f"{i}. <b>{n}</b> — {fmt(b)}$ | {r} реф\n"
    await cb.message.edit_text(text, reply_markup=kb_admin(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "ad_bonus_help")
async def cb_ad_bonus_help(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    await cb.message.answer(
        "🎁 <b>Выдача бонуса</b>\n\n"
        "1️⃣ Ответом: <code>/bonus 10</code>\n"
        "2️⃣ По @username: <code>/bonus @user 10</code>",
        parse_mode="HTML"
    )
    await cb.answer()

@dp.message(Command("bonus"))
async def cmd_bonus(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    args = m.text.split()
    tid = None; amt = None
    if m.reply_to_message and len(args) >= 2:
        tid = m.reply_to_message.from_user.id
        try: amt = float(args[1])
        except: return
    elif len(args) >= 3 and args[1].startswith("@"):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT uid FROM users WHERE LOWER(username)=?", (args[1].lower(),))
        r = c.fetchone(); conn.close()
        if not r: await m.answer("❌ Не найден"); return
        tid = r[0]
        try: amt = float(args[2])
        except: return
    else:
        await m.answer("📋 /bonus 10 (ответом) или /bonus @user 10"); return
    u = db_get(tid)
    nb = round(u["balance"] + amt, 2)
    db_upd(tid, balance=nb)
    await m.answer(f"✅ <b>{u['username']}</b> +{amt}$ → {fmt(nb)}$", parse_mode="HTML")
    try: await bot.send_message(tid, f"🎁 Бонус: +{amt}$")
    except: pass

# ==================== NOOP ====================
@dp.callback_query(F.data == "noop")
async def cb_noop(cb: types.CallbackQuery):
    await cb.answer()

# ==================== MAIN ====================
async def main():
    db_init()
    print("="*40)
    print("🎰 STAVKA BOT запущен!")
    me = await bot.get_me()
    print(f"Бот: @{me.username}")
    print("="*40)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹ Остановлен")
