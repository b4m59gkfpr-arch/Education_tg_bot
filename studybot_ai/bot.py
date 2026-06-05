from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from studybot_ai.config import load_environment
from studybot_ai.database import (
    get_or_create_user,
    get_subject,
    get_user_stats,
    init_db,
    list_notes,
    list_questions,
    list_subjects,
    save_result,
    
    # Group onboarding functions
    list_all_groups,
    get_group,
    update_user_group_and_name,
    clear_user_group,
)


load_environment()


router = Router()
quiz_sessions: dict[int, dict] = {}
registration_sessions: dict[int, dict] = {}


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Предметы"), KeyboardButton(text="📝 Конспекты")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🚪 Выйти из группы")],
    ],
    resize_keyboard=True,
)


def get_groups_keyboard() -> InlineKeyboardMarkup:
    groups = list_all_groups()
    buttons = [
        [InlineKeyboardButton(text=f"Группа {g['name']}", callback_data=f"select_group:{g['id']}")]
        for g in groups
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subjects_keyboard(prefix: str, group_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=subject["name"], callback_data=f"{prefix}:{subject['id']}")]
        for subject in list_subjects(group_id)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def answers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="A", callback_data="answer:A"),
                InlineKeyboardButton(text="B", callback_data="answer:B"),
                InlineKeyboardButton(text="C", callback_data="answer:C"),
                InlineKeyboardButton(text="D", callback_data="answer:D"),
            ]
        ]
    )


async def send_question(message_or_call: Message | CallbackQuery, telegram_id: int) -> None:
    session = quiz_sessions[telegram_id]
    question = session["questions"][session["index"]]
    text = (
        f"{session['index'] + 1}/{len(session['questions'])}\n\n"
        f"{question['question']}\n\n"
        f"A. {question['option_a']}\n"
        f"B. {question['option_b']}\n"
        f"C. {question['option_c']}\n"
        f"D. {question['option_d']}"
    )

    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=answers_keyboard())
    else:
        await message_or_call.answer(text, reply_markup=answers_keyboard())


# Registration Checking Filter
def check_not_registered(message: Message) -> bool:
    telegram_id = message.from_user.id
    if telegram_id in registration_sessions:
        return True

    user = get_or_create_user(telegram_id, message.from_user.username)
    group_id = user.get("group_id")
    if group_id is not None:
        group = get_group(group_id)
        if not group:
            clear_user_group(telegram_id)
            user = get_or_create_user(telegram_id, message.from_user.username)
            
    return user.get("group_id") is None or user.get("full_name") is None


# Onboarding handlers for unregistered users
@router.message(check_not_registered)
async def handle_registration(message: Message) -> None:
    telegram_id = message.from_user.id
    session = registration_sessions.get(telegram_id)
    
    # Check if the message is a /start command with a payload (deep link)
    if message.text and message.text.startswith("/start"):
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()
            if arg.isdigit():
                group_id = int(arg)
                group = get_group(group_id)
                if group:
                    registration_sessions[telegram_id] = {
                        "step": "enter_name",
                        "group_id": group_id
                    }
                    await message.answer(
                        f"Привет! Вы перешли по ссылке-приглашению в группу: {group['name']}.\n\n"
                        "Пожалуйста, введите ваше ФИО (Фамилия Имя Отчество) для завершения регистрации:",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
                else:
                    await message.answer("Указанная в ссылке группа не найдена.")
            else:
                await message.answer("Неверный формат ссылки-приглашения.")
    
    if session and session.get("step") == "enter_name":
        group_id = session["group_id"]
        group = get_group(group_id)
        if not group:
            registration_sessions.pop(telegram_id, None)
            groups = list_all_groups()
            if not groups:
                await message.answer(
                    "К сожалению, выбранная группа была удалена преподавателем, и в базе больше нет учебных групп.\n"
                    "Пожалуйста, обратитесь к вашему преподавателю.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            await message.answer(
                "К сожалению, выбранная группа была удалена преподавателем.",
                reply_markup=ReplyKeyboardRemove()
            )
            await message.answer(
                "Пожалуйста, выберите другую группу:",
                reply_markup=get_groups_keyboard()
            )
            return
            
        full_name = message.text.strip()
        if len(full_name) < 2:
            await message.answer("Пожалуйста, введите настоящее корректное имя (ФИО).")
            return
            
        update_user_group_and_name(telegram_id, group_id, full_name)
        registration_sessions.pop(telegram_id, None)
        
        group_name = group["name"]
        
        await message.answer(
            f"Регистрация завершена!\n\n"
            f"Имя: {full_name}\n"
            f"Группа: {group_name}",
            reply_markup=main_keyboard
        )
    else:
        groups = list_all_groups()
        if not groups:
            await message.answer(
                "Привет! К сожалению, преподаватель пока не создал ни одной учебной группы в админке.\n"
                "Пожалуйста, обратитесь к вашему преподавателю.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
            
        registration_sessions[telegram_id] = {"step": "select_group"}
        await message.answer(
            "Привет! Для начала работы с ботом...",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer(
            "Пожалуйста, выберите свою учебную группу:",
            reply_markup=get_groups_keyboard()
        )


@router.callback_query(F.data.startswith("select_group:"))
async def select_group_callback(call: CallbackQuery) -> None:
    group_id = int(call.data.split(":")[1])
    telegram_id = call.from_user.id
    
    group = get_group(group_id)
    if not group:
        await call.message.answer(
            "Эта группа была удалена преподавателем. Пожалуйста, выберите другую группу:",
            reply_markup=get_groups_keyboard()
        )
        await call.answer()
        return
        
    registration_sessions[telegram_id] = {
        "step": "enter_name",
        "group_id": group_id
    }
    
    group_name = group["name"]
    
    await call.message.answer(
        f"Вы выбрали группу: {group_name}.\n\n"
        "Теперь введите ваше ФИО (Фамилия Имя Отчество):",
        reply_markup=ReplyKeyboardRemove()
    )
    await call.answer()


# Standard Handlers (Registered Users Only)
@router.message(CommandStart())
async def start(message: Message, command: CommandObject) -> None:
    telegram_id = message.from_user.id
    args = command.args
    
    if args:
        arg = args.strip()
        if arg.isdigit():
            group_id = int(arg)
            group = get_group(group_id)
            if group:
                user = get_or_create_user(telegram_id, message.from_user.username)
                if user.get("group_id") == group_id:
                    await message.answer(
                        f"Вы уже зарегистрированы в группе {group['name']}.",
                        reply_markup=main_keyboard
                    )
                    return
                
                # Initiate transition
                registration_sessions[telegram_id] = {
                    "step": "enter_name",
                    "group_id": group_id
                }
                quiz_sessions.pop(telegram_id, None)
                await message.answer(
                    f"Вы переходите в группу: {group['name']}.\n\n"
                    "Для подтверждения перехода, пожалуйста, введите ваше ФИО (Фамилия Имя Отчество):",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            else:
                await message.answer("Группа по ссылке-приглашению не найдена.")
        else:
            await message.answer("Неверный формат ссылки-приглашения.")

    user = get_or_create_user(telegram_id, message.from_user.username)
    group = get_group(user["group_id"])
    group_name = group["name"] if group else "Неизвестно"
    
    await message.answer(
        f"Привет, {user['full_name']}!\n\n"
        f"Группа: {group_name}\n"
        "Рад видеть вас снова. Используйте меню для прохождения тестов и конспектов.",
        reply_markup=main_keyboard,
    )


@router.message(F.text == "🚪 Выйти из группы")
async def leave_group_handler(message: Message) -> None:
    telegram_id = message.from_user.id
    clear_user_group(telegram_id)
    quiz_sessions.pop(telegram_id, None)
    registration_sessions[telegram_id] = {"step": "select_group"}
    
    await message.answer("Вы вышли из группы.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Пожалуйста, выберите новую учебную группу:",
        reply_markup=get_groups_keyboard()
    )


@router.message(F.text == "📚 Предметы")
async def show_subjects(message: Message) -> None:
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    group_id = user["group_id"]
    subjects = list_subjects(group_id)
    if not subjects:
        await message.answer("Пока нет предметов для вашей группы.")
        return

    await message.answer("Выберите предмет для теста:", reply_markup=subjects_keyboard("quiz_subject", group_id))


@router.callback_query(F.data.startswith("quiz_subject:"))
async def start_quiz(call: CallbackQuery) -> None:
    subject_id = int(call.data.split(":")[1])
    user = get_or_create_user(call.from_user.id, call.from_user.username)
    group_id = user["group_id"]

    subject = get_subject(subject_id)
    if not subject or subject["group_id"] != group_id:
        await call.message.answer("Доступ запрещен.")
        await call.answer()
        return

    questions = list_questions(subject_id, group_id=group_id, limit=10)
    if not questions:
        await call.message.answer("По этому предмету пока нет вопросов.")
        await call.answer()
        return

    quiz_sessions[call.from_user.id] = {
        "subject_id": subject_id,
        "questions": questions,
        "index": 0,
        "score": 0,
    }

    await call.message.answer(f"Тест по предмету: {subject['name']}")
    await send_question(call, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("answer:"))
async def answer_question(call: CallbackQuery) -> None:
    session = quiz_sessions.get(call.from_user.id)
    if not session:
        await call.message.answer("Тест не найден. Нажмите «📚 Предметы», чтобы начать заново.")
        await call.answer()
        return

    selected_answer = call.data.split(":")[1]
    question = session["questions"][session["index"]]
    correct_answer = question["correct_answer"]

    if selected_answer == correct_answer:
        session["score"] += 1
        await call.message.answer("✅ Верно")
    else:
        await call.message.answer(f"❌ Неверно\nПравильный ответ: {correct_answer}")

    session["index"] += 1

    if session["index"] >= len(session["questions"]):
        score = session["score"]
        total = len(session["questions"])
        percent = round(score / total * 100)
        save_result(call.from_user.id, session["subject_id"], score, total)
        quiz_sessions.pop(call.from_user.id, None)

        await call.message.answer(
            f"Ваш результат:\n\n{score} из {total}\n{percent}%",
            reply_markup=main_keyboard,
        )
    else:
        await send_question(call, call.from_user.id)

    await call.answer()


@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message) -> None:
    stats = get_user_stats(message.from_user.id)
    await message.answer(
        "📊 Статистика\n\n"
        f"Всего тестов: {stats['total_tests']}\n"
        f"Средний балл: {stats['average_percent']}%\n"
        f"Лучший результат: {stats['best_percent']}%"
    )


@router.message(F.text == "📝 Конспекты")
async def show_note_subjects(message: Message) -> None:
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    group_id = user["group_id"]
    subjects = list_subjects(group_id)
    if not subjects:
        await message.answer("Пока нет конспектов для вашей группы.")
        return

    await message.answer("Выберите предмет для конспекта:", reply_markup=subjects_keyboard("notes_subject", group_id))


@router.callback_query(F.data.startswith("notes_subject:"))
async def show_notes(call: CallbackQuery) -> None:
    subject_id = int(call.data.split(":")[1])
    user = get_or_create_user(call.from_user.id, call.from_user.username)
    group_id = user["group_id"]

    subject = get_subject(subject_id)
    if not subject or subject["group_id"] != group_id:
        await call.message.answer("Доступ запрещен.")
        await call.answer()
        return

    notes = list_notes(subject_id, group_id=group_id)
    if not notes:
        await call.message.answer("По этому предмету пока нет конспектов.")
        await call.answer()
        return

    for note in notes:
        await call.message.answer(f"📌 {note['title']}\n\n{note['content']}")

    await call.answer()


# Catch-All Handler
@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer(
        "Такой команды нет. Пожалуйста, используйте кнопки меню или команду /start.",
        reply_markup=main_keyboard,
    )


async def main() -> None:
    init_db()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
