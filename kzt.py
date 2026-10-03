import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

# ====== Премиум emoji ID-лері (өз ID-леріңізге ауыстырыңыз) ======
# ID алу үшін: ботқа премиум emoji жіберіңіз - ол ID-ін қайтарады
EMOJI_START = "5445284980978621387"   # старт кнопкасындағы иконка
EMOJI_OK = "5445284980978621387"
EMOJI_BAD = "5445284980978621387"
EMOJI_RESTART = "5445284980978621387"
# <tg-emoji> мәтінде көрінуі үшін fallback ретінде кәдімгі emoji қойылады
TEXT_EMOJI = '<tg-emoji emoji-id="5445284980978621387">🎯</tg-emoji>'

# ====== Сұрақтар: (сұрақ, [жауаптар], дұрыс жауап индексі) ======
QUESTIONS = [
    ("Қазақстанның астанасы қай қала?", ["Алматы", "Астана", "Шымкент"], 1),
    ("2 + 2 × 2 = ?", ["8", "6", "4"], 1),
    ("Python-да тізімге элемент қосатын әдіс?", ["add()", "push()", "append()"], 2),
    ("Telegram қай жылы құрылды?", ["2013", "2010", "2016"], 0),
    ("Жер Күнді айналып шығады, ол қанша уақыт?", ["1 ай", "1 жыл", "1 апта"], 1),
]

router = Router()
# user_id -> {"q": ағымдағы сұрақ нөмірі, "score": ұпай}
progress: dict[int, dict] = {}


# ---------- Клавиатуралар ----------
def start_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Тестті бастау»"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Тестті бастау",
            callback_data="start_test",
            style="primary",
            icon_custom_emoji_id=EMOJI_START,
        )
    )
    return builder.as_markup()


def question_keyboard(q_index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, answer in enumerate(QUESTIONS[q_index][1]):
        builder.row(
            InlineKeyboardButton(
                text=answer,
                callback_data=f"ans:{q_index}:{i}",
                style="default",
            )
        )
    return builder.as_markup()


def next_keyboard(is_last: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Нәтижені көру" if is_last else "Келесі сұрақ",
            callback_data="next",
            style="success",
            icon_custom_emoji_id=EMOJI_OK,
        )
    )
    return builder.as_markup()


def restart_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Тестті қайта өту»"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Тестті қайта өту",
            callback_data="start_test",
            style="danger",
            icon_custom_emoji_id=EMOJI_RESTART,
        )
    )
    return builder.as_markup()


# ---------- Көмекші ----------
async def send_question(message: Message, user_id: int) -> None:
    q = progress[user_id]["q"]
    text = f"{TEXT_EMOJI} <b>Сұрақ {q + 1}/{len(QUESTIONS)}</b>\n\n{QUESTIONS[q][0]}"
    await message.edit_text(text, reply_markup=question_keyboard(q))


# ---------- Хэндлерлер ----------
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"{TEXT_EMOJI} <b>Тест ботына қош келдіңіз!</b>\n\n"
        f"{len(QUESTIONS)} сұраққа жауап беріп, білімді тексеріңіз.\n"
        "Бастау үшін төмендегі кнопканы басыңыз.\n\n"
        "💡 Премиум emoji ID-ін білгіңіз келсе, ботқа сол emoji-ді жіберіңіз.",
        reply_markup=start_keyboard(),
    )


@router.callback_query(F.data == "start_test")
async def start_test(call: CallbackQuery):
    progress[call.from_user.id] = {"q": 0, "score": 0}
    await send_question(call.message, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("ans:"))
async def answer(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in progress:
        await call.answer("Тестті қайта бастаңыз: /start", show_alert=True)
        return

    _, q_str, a_str = call.data.split(":")
    q_index, a_index = int(q_str), int(a_str)

    # ескі сұраққа қайта басудан қорғау
    if q_index != progress[user_id]["q"]:
        await call.answer()
        return

    question, answers, correct = QUESTIONS[q_index]
    is_correct = a_index == correct
    if is_correct:
        progress[user_id]["score"] += 1

    # Жауаптарды түспен көрсету: дұрысы - жасыл, қателігі - қызыл
    builder = InlineKeyboardBuilder()
    for i, ans in enumerate(answers):
        if i == correct:
            style = "success"
        elif i == a_index:
            style = "danger"
        else:
            style = "default"
        builder.row(InlineKeyboardButton(text=ans, callback_data="noop", style=style))
    is_last = q_index == len(QUESTIONS) - 1
    builder.attach(InlineKeyboardBuilder.from_markup(next_keyboard(is_last)))

    verdict = "✅ Дұрыс!" if is_correct else f"❌ Қате. Дұрыс жауап: <b>{answers[correct]}</b>"
    await call.message.edit_text(
        f"<b>Сұрақ {q_index + 1}/{len(QUESTIONS)}</b>\n\n{question}\n\n{verdict}",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "next")
async def next_question(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in progress:
        await call.answer("Тестті қайта бастаңыз: /start", show_alert=True)
        return

    progress[user_id]["q"] += 1
    if progress[user_id]["q"] >= len(QUESTIONS):
        score = progress[user_id]["score"]
        total = len(QUESTIONS)
        percent = round(score / total * 100)
        await call.message.edit_text(
            f"{TEXT_EMOJI} <b>Тест аяқталды!</b>\n\n"
            f"Нәтиже: <b>{score}/{total}</b> ({percent}%)",
            reply_markup=restart_keyboard(),
        )
        progress.pop(user_id, None)
    else:
        await send_question(call.message, user_id)
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


# ---------- Премиум emoji конвертері ----------
@router.message(F.entities)
async def emoji_converter(message: Message):
    ids = [e.custom_emoji_id for e in message.entities if e.type == "custom_emoji"]
    if not ids:
        return
    await message.answer("\n".join(f"<code>{i}</code>" for i in ids))


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
