import asyncio
import logging
import sys
import re
from datetime import datetime, time, date, timezone, timedelta
from aiogram import Bot, Dispatcher, html, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, KeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext

class Survey(StatesGroup):
    name = State()
    age = State()
    city = State()
    disp_state = State()
    local_time = State()
    timezone = State()
    clothes_choice = State()


TOKEN = "8582666055:AAEH0QVbIAsmAfHV4EUN92333ojX_CPB0ck"

dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def name_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Назовите ваше имя")
    await state.set_state(Survey.name)

@dp.message(Survey.name)
async def age_handler(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer("Сколько вам лет?")
    await state.set_state(Survey.age)

@dp.message(Survey.city)
async def city_handler(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await message.answer("В каком городе вы живёте?")
    await state.set_state(Survey.city)

@dp.message(Survey.disp_state)
async def disp_handler(message: Message, state: FSMContext) -> None:
    answer = message.text.lower().strip()

    if answer == "да":
        await state.update_data(has_license=True)
        await message.answer("В какое время вы хотите получать сводку (формат ЧЧ:ММ с шагом 30 минут, например 08:30)")
        await state.set_state(Survey.drive_time)

    elif answer == "нет":
        await state.update_data(has_license=False)
        await state.set_state(Survey.final)
        await message.answer("Хорошо, идём дальше")

    else:
        await message.answer("Пожалуйста, ответьте 'да' или 'нет'")

@dp.message(Survey.timezone)
async def go_to_timezone(message: Message, state: FSMContext):
    await message.answer(
        "Укажите свой часовой пояс относительно UTC.\n"
        "Примеры: UTC+2, UTC-5, +03:00"
    )
    await state.set_state(Survey.ask_timezone)

@dp.message(Survey.timezone)
async def timezone_handler(message: Message, state: FSMContext):
    text = message.text.strip().upper()

    match = re.match(r"(UTC)?([+-])(\d{1,2})(?::(\d{2}))?$", text)
    if not match:
        await message.answer(
            "Неверный формат.\n"
            "Примеры: UTC+2, UTC-5, +03:00"
        )
        return

    sign = 1 if match.group(2) == "+" else -1
    hours = int(match.group(3))
    minutes = int(match.group(4) or 0)

    if hours > 14 or minutes >= 60:
        await message.answer("Некорректное смещение UTC.")
        return

    offset = timedelta(hours=hours, minutes=minutes) * sign
    tz = timezone(offset)

    await state.update_data(user_tz=tz)

    await message.answer(
        "Теперь введите локальное время "
        "в формате ЧЧ:ММ с шагом 30 минут (например, 08:30)."
    )
    await state.set_state(Survey.local_time)

@dp.message(Survey.ask_time)
async def time_handler(message: Message, state: FSMContext):
    try:
        hours, minutes = map(int, message.text.split(":"))
        if not (0 <= hours <= 23 and minutes not in (0, 30)):
            raise ValueError
    except ValueError:
        await message.answer("Введите время в формате ЧЧ:ММ с шагом 30 минут.")
        return

    data = await state.get_data()
    user_tz = data["user_tz"]

    local_dt = datetime.combine(
        date.today(),
        time(hour=hours, minute=minutes),
        tzinfo=user_tz
    )

    utc_dt = local_dt.astimezone(timezone)

    await state.update_data(time_utc=utc_dt)

    await message.answer(
        f"Принято.\n"
        f"Ваше время в UTC: {utc_dt.strftime('%H:%M')}"
    )

    await state.set_state(Survey.next_state)

async def send_clothes_images(message: Message):
    media = [
        InputMediaPhoto(media="clothes1.jpg"),
        InputMediaPhoto(media="clothes1.jpg"),
        InputMediaPhoto(media="clothes1.jpg"),
    ]

    await message.answer_media_group(media)

@dp.message(Survey.car_choice)
async def car_choice_handler(message: Message, state: FSMContext):
    if message.text not in (str(i) for i in range(1, 11)):
        await message.answer("Пожалуйста, выбери один из предложенных вариантов.")
        return

    await state.update_data(car_choice=int(message.text))
    await state.set_state(Survey.final)
    await message.answer("Отличный выбор!")

async def main() -> None:
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # And the run events dispatching
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())