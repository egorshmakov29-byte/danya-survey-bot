import asyncio
import csv
import html
import logging
import os
import sqlite3
from datetime import datetime
from io import StringIO

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬТЕ_СЮДА_ТОКЕН_БОТА")
ADMIN_IDS = {
    int(item.strip())
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if item.strip().isdigit()
}
DB_NAME = "survey.sqlite3"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =========================
# БАЗА ДАННЫХ SQLITE
# =========================

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                full_name TEXT,
                gender TEXT NOT NULL,
                age TEXT NOT NULL,
                region TEXT NOT NULL,
                occupation TEXT NOT NULL,
                current_income TEXT NOT NULL,
                target_income TEXT NOT NULL,
                youtube_interest TEXT NOT NULL,
                youtube_experience TEXT NOT NULL,
                training_interest TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_response(user, answers):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT INTO responses (
                user_id, username, full_name, gender, age, region,
                occupation, current_income, target_income,
                youtube_interest, youtube_experience, training_interest,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                gender=excluded.gender,
                age=excluded.age,
                region=excluded.region,
                occupation=excluded.occupation,
                current_income=excluded.current_income,
                target_income=excluded.target_income,
                youtube_interest=excluded.youtube_interest,
                youtube_experience=excluded.youtube_experience,
                training_interest=excluded.training_interest,
                created_at=excluded.created_at
            """,
            (
                user.id,
                user.username or "",
                user.full_name or "",
                answers["gender"],
                answers["age"],
                answers["region"],
                answers["occupation"],
                answers["current_income"],
                answers["target_income"],
                answers["youtube_interest"],
                answers["youtube_experience"],
                answers["training_interest"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()


def get_stats():
    with sqlite3.connect(DB_NAME) as conn:
        total = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM responses WHERE date(created_at) = date('now', 'localtime')"
        ).fetchone()[0]
    return total, today


def get_all_responses():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT user_id, username, full_name, gender, age, region,
                   occupation, current_income, target_income,
                   youtube_interest, youtube_experience, training_interest,
                   created_at
            FROM responses
            ORDER BY id DESC
            """
        ).fetchall()


# =========================
# СОСТОЯНИЯ АНКЕТЫ
# =========================

class Survey(StatesGroup):
    gender = State()
    age = State()
    region = State()
    region_custom = State()
    occupation = State()
    current_income = State()
    target_income = State()
    youtube_interest = State()
    youtube_experience = State()
    training_interest = State()


# =========================
# КНОПКИ И ВОПРОСЫ
# =========================

def make_keyboard(options, field):
    # В callback_data передаём короткий индекс, чтобы не превышать лимит Telegram в 64 байта.
    rows = []
    for index, option in enumerate(options):
        rows.append([
            InlineKeyboardButton(
                text=option,
                callback_data=f"answer:{field}:{index}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


ANSWER_OPTIONS = {
    "gender": GENDER_OPTIONS,
    "age": AGE_OPTIONS,
    "region": REGION_OPTIONS,
    "occupation": OCCUPATION_OPTIONS,
    "current_income": INCOME_OPTIONS,
    "youtube_interest": YOUTUBE_INTEREST_OPTIONS,
    "youtube_experience": YOUTUBE_EXPERIENCE_OPTIONS,
    "training_interest": TRAINING_OPTIONS,
}


GENDER_OPTIONS = ["Мужской", "Женский"]

AGE_OPTIONS = [
    "До 18 лет",
    "18–21 год",
    "22–25 лет",
    "26–30 лет",
    "30+",
]

REGION_OPTIONS = [
    "Россия",
    "Беларусь",
    "Казахстан",
    "Украина",
    "Другая страна",
]

OCCUPATION_OPTIONS = [
    "Работаю в найме",
    "Работаю на себя / фриланс",
    "Предприниматель / владелец бизнеса",
    "Учусь в университете / колледже",
    "Учусь в школе",
    "Совмещаю работу и учёбу",
    "Временно не работаю",
    "Другое",
]

INCOME_OPTIONS = [
    "Пока нет дохода",
    "До 30 000 ₽",
    "30 000–50 000 ₽",
    "50 000–100 000 ₽",
    "100 000–150 000 ₽",
    "150 000–300 000 ₽",
    "300 000 ₽+",
]

YOUTUBE_INTEREST_OPTIONS = [
    "Да, уже занимаюсь этим",
    "Изучаю тему, но пока не начал",
    "Только планирую начать",
    "Слышал об этом, хочу разобраться",
    "Пока просто интересно",
]

YOUTUBE_EXPERIENCE_OPTIONS = [
    "Полный новичок",
    "Пробовал создавать видео, но без результата",
    "Есть опыт ведения каналов",
    "Уже получаю просмотры и аудиторию",
    "Есть опыт монетизации каналов",
]

TRAINING_OPTIONS = [
    "Да",
    "Возможно, рассматриваю такую возможность",
    "Нет, пока хочу разобраться самостоятельно",
]


async def ask_gender(message: Message, state: FSMContext):
    await state.set_state(Survey.gender)
    await message.answer(
        "<b>1. Ваш пол?</b>",
        reply_markup=make_keyboard(GENDER_OPTIONS, "gender"),
    )


async def ask_age(message: Message, state: FSMContext):
    await state.set_state(Survey.age)
    await message.answer(
        "<b>2. Сколько вам лет?</b>",
        reply_markup=make_keyboard(AGE_OPTIONS, "age"),
    )


async def ask_region(message: Message, state: FSMContext):
    await state.set_state(Survey.region)
    await message.answer(
        "<b>3. Из какой вы страны / региона?</b>",
        reply_markup=make_keyboard(REGION_OPTIONS, "region"),
    )


async def ask_occupation(message: Message, state: FSMContext):
    await state.set_state(Survey.occupation)
    await message.answer(
        "<b>4. Чем вы сейчас занимаетесь?</b>",
        reply_markup=make_keyboard(OCCUPATION_OPTIONS, "occupation"),
    )


async def ask_current_income(message: Message, state: FSMContext):
    await state.set_state(Survey.current_income)
    await message.answer(
        "<b>5. Какой у вас сейчас ежемесячный доход?</b>",
        reply_markup=make_keyboard(INCOME_OPTIONS, "current_income"),
    )


async def ask_target_income(message: Message, state: FSMContext):
    await state.set_state(Survey.target_income)
    await message.answer(
        "<b>6. Сколько вы хотели бы зарабатывать в месяц?</b>\n\n"
        "Напишите желаемую сумму, например: <i>200 000 ₽</i>.",
    )


async def ask_youtube_interest(message: Message, state: FSMContext):
    await state.set_state(Survey.youtube_interest)
    await message.answer(
        "<b>7. Интересовались ли вы заработком на зарубежном YouTube?</b>",
        reply_markup=make_keyboard(YOUTUBE_INTEREST_OPTIONS, "youtube_interest"),
    )


async def ask_youtube_experience(message: Message, state: FSMContext):
    await state.set_state(Survey.youtube_experience)
    await message.answer(
        "<b>8. Какой у вас опыт в создании YouTube-контента?</b>",
        reply_markup=make_keyboard(YOUTUBE_EXPERIENCE_OPTIONS, "youtube_experience"),
    )


async def ask_training_interest(message: Message, state: FSMContext):
    await state.set_state(Survey.training_interest)
    await message.answer(
        "<b>9. Рассматривали бы вы возможность пройти обучение "
        "по созданию и монетизации зарубежных YouTube-каналов?</b>",
        reply_markup=make_keyboard(TRAINING_OPTIONS, "training_interest"),
    )


# =========================
# ЗАПУСК И ПРОХОЖДЕНИЕ АНКЕТЫ
# =========================

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пройти опрос", callback_data="survey:start")]
        ]
    )
    await message.answer(
        "Привет! Мы проводим небольшой опрос, чтобы лучше понять аудиторию "
        "и интерес к зарубежному YouTube.\n\n"
        "Анкета состоит из 9 коротких вопросов. Ответы будут использованы "
        "для анализа аудитории.\n\n"
        "Нажимая «Пройти опрос», вы соглашаетесь на сохранение своих ответов "
        "для этой цели.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "survey:start")
async def start_survey(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.update_data(answers={})
    await callback.message.answer("Отлично, начинаем!")
    await ask_gender(callback.message, state)


@dp.callback_query(F.data.startswith("answer:"))
async def process_answer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()

    try:
        _, field, option_index = callback.data.split(":", 2)
        value = ANSWER_OPTIONS[field][int(option_index)]
    except (ValueError, KeyError, IndexError):
        await callback.answer("Не удалось распознать ответ. Попробуйте ещё раз.", show_alert=True)
        return

    expected_states = {
        "gender": Survey.gender.state,
        "age": Survey.age.state,
        "region": Survey.region.state,
        "occupation": Survey.occupation.state,
        "current_income": Survey.current_income.state,
        "youtube_interest": Survey.youtube_interest.state,
        "youtube_experience": Survey.youtube_experience.state,
        "training_interest": Survey.training_interest.state,
    }

    if field not in expected_states or current_state != expected_states[field]:
        await callback.answer("Этот ответ уже неактуален. Продолжите с текущего вопроса.", show_alert=True)
        return

    data = await state.get_data()
    answers = data.get("answers", {})
    answers[field] = value
    await state.update_data(answers=answers)

    if field == "gender":
        await ask_age(callback.message, state)
    elif field == "age":
        await ask_region(callback.message, state)
    elif field == "region":
        if value == "Другая страна":
            await state.set_state(Survey.region_custom)
            await callback.message.answer("Напишите название вашей страны или региона:")
        else:
            answers["region"] = value
            await state.update_data(answers=answers)
            await ask_occupation(callback.message, state)
    elif field == "occupation":
        await ask_current_income(callback.message, state)
    elif field == "current_income":
        await ask_target_income(callback.message, state)
    elif field == "youtube_interest":
        await ask_youtube_experience(callback.message, state)
    elif field == "youtube_experience":
        await ask_training_interest(callback.message, state)
    elif field == "training_interest":
        user_data = await state.get_data()
        final_answers = user_data.get("answers", {})
        save_response(callback.from_user, final_answers)
        await state.clear()
        await callback.message.answer(
            "Спасибо! Вы успешно прошли опрос.\n\n"
            "Ваши ответы сохранены. Хорошего дня!"
        )


@dp.message(Survey.region_custom)
async def process_custom_region(message: Message, state: FSMContext):
    region = message.text.strip()
    if not region or len(region) > 100:
        await message.answer("Пожалуйста, укажите страну или регион текстом (до 100 символов).")
        return

    data = await state.get_data()
    answers = data.get("answers", {})
    answers["region"] = region
    await state.update_data(answers=answers)
    await ask_occupation(message, state)


@dp.message(Survey.target_income)
async def process_target_income(message: Message, state: FSMContext):
    target_income = (message.text or "").strip()
    if not target_income or len(target_income) > 100:
        await message.answer("Напишите желаемую сумму (до 100 символов). Например: 200 000 ₽.")
        return

    data = await state.get_data()
    answers = data.get("answers", {})
    answers["target_income"] = target_income
    await state.update_data(answers=answers)
    await ask_youtube_interest(message, state)


@dp.message(Command("cancel"))
async def cancel_survey(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Опрос отменён. Если захотите пройти его позже, нажмите /start.")


# =========================
# КОМАНДЫ АДМИНИСТРАТОРА
# =========================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@dp.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    total, today = get_stats()
    await message.answer(
        f"<b>Статистика опроса</b>\n\n"
        f"Всего заполненных анкет: <b>{total}</b>\n"
        f"Заполнено сегодня: <b>{today}</b>"
    )


@dp.message(Command("export"))
async def admin_export(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = get_all_responses()
    if not rows:
        await message.answer("Пока нет заполненных анкет.")
        return

    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Telegram ID",
        "Username",
        "Имя",
        "Пол",
        "Возраст",
        "Страна / регион",
        "Занятость",
        "Текущий доход",
        "Желаемый доход",
        "Интерес к YouTube",
        "Опыт YouTube",
        "Интерес к обучению",
        "Дата заполнения",
    ])

    for row in rows:
        writer.writerow(list(row))

    file_data = output.getvalue().encode("utf-8-sig")
    document = BufferedInputFile(file_data, filename="survey_responses.csv")
    await message.answer_document(
        document,
        caption=f"Выгрузка анкет: {len(rows)} записей.",
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "<b>Команды администратора</b>\n"
            "/stats — количество заполненных анкет\n"
            "/export — выгрузить все ответы в CSV\n"
            "/start — пройти анкету заново"
        )
    else:
        await message.answer(
            "Чтобы пройти опрос, нажмите /start.\n"
            "Чтобы остановить заполнение, отправьте /cancel."
        )


# =========================
# ЗАПУСК БОТА
# =========================

async def main():
    if BOT_TOKEN == "ВСТАВЬТЕ_СЮДА_ТОКЕН_БОТА" or not BOT_TOKEN.strip():
        raise RuntimeError(
            "Укажите токен бота в BOT_TOKEN или через переменную окружения."
        )

    init_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
