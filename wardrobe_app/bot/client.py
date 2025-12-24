import asyncio
import sys

from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext

from wardrobe_app.database.connection import get_db, init_db, close_db
from wardrobe_app.database.models import Gender, User, UserPreferences
from wardrobe_app.bot.keyboards import get_style_choice_keyboard, STYLE_NAMES, STYLE_TO_NUMBER
from wardrobe_app.config import settings
from wardrobe_app.services.recommendation import main_rec

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from wardrobe_app.database.connection import AsyncSessionLocal

import logging
from geopy.geocoders import Nominatim
from geopy.adapters import AioHTTPAdapter
from geopy.exc import GeocoderTimedOut, GeocoderServiceError


async def validate_city_with_weather_api(city_name: str) -> tuple[bool, dict | None]:
    """
    Проверяет существование города через Nominatim (OpenStreetMap) с помощью geopy.
    Возвращает (статус_успеха, данные_города) или (False, None).

    Данные включают:
    - normalized_city: нормализованное название города
    - full_address: полный адрес
    - latitude, longitude
    - raw: полный ответ от Nominatim
    """
    try:
        async with Nominatim(
                user_agent="my_city_validator_app",
                adapter_factory=AioHTTPAdapter,
                timeout=10
        ) as geolocator:
            location = await geolocator.geocode(
                city_name,
                exactly_one=True,
                addressdetails=True,
                language="ru"
            )

        if location is None:
            logging.warning(f"Город '{city_name}' не найден в Nominatim")
            return False, None

        address = location.raw.get('address', {})
        normalized_city = (
                address.get('city') or
                address.get('town') or
                address.get('village') or
                address.get('county') or
                address.get('state') or
                location.address.split(',')[0].strip()
        )

        data = {
            'normalized_city': normalized_city,
            'full_address': location.address,
            'latitude': location.latitude,
            'longitude': location.longitude,
            'raw': location.raw
        }

        return True, data

    except GeocoderTimedOut:
        logging.error(f"Таймаут при проверке города '{city_name}' в Nominatim")
        return False, None
    except GeocoderServiceError as e:
        logging.error(f"Ошибка сервиса Nominatim для города '{city_name}': {e}")
        return False, None
    except Exception as e:
        logging.error(f"Неизвестная ошибка при валидации города '{city_name}': {e}")
        return False, None


class Survey(StatesGroup):
    name = State()
    gender = State()
    city = State()
    enable_dispatch = State()
    local_time = State()
    clothes_style = State()


dp = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()

    await message.answer(
        "Добро пожаловать в Гардеробный бот!\n"
        "Я помогу вам подобрать одежду по погоде.\n\n"
        "Давайте пройдем короткий опрос для настройки.\n\n"
        "1. Как вас зовут?"
    )
    await state.set_state(Survey.name)


@dp.message(Survey.name)
async def process_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите имя (минимум 2 символа).")
        return

    await state.update_data(name=name)

    await message.answer(
        f"Приятно познакомиться, {name}!\n\n"
        "2. Укажите ваш пол для более точных рекомендаций:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Мужской", callback_data="gender_male")],
                [InlineKeyboardButton(text="Женский", callback_data="gender_female")]
            ]
        )
    )
    await state.set_state(Survey.gender)


@dp.callback_query(F.data.startswith("gender_"))
async def process_gender(callback: CallbackQuery, state: FSMContext):
    gender_map = {
        "gender_male": Gender.MALE,
        "gender_female": Gender.FEMALE
    }

    selected = gender_map.get(callback.data)
    if not selected:
        await callback.answer("Ошибка выбора пола")
        return

    await state.update_data(gender=selected)

    await callback.message.edit_text(
        f"Пол выбран: {'Мужской' if selected == Gender.MALE else 'Женский'}"
    )

    await callback.message.answer(
        "3. В каком городе вы живете?\n"
        "Например: Москва, Санкт-Петербург, London"
    )
    await state.set_state(Survey.city)
    await callback.answer()


@dp.message(Survey.city)
async def process_city(message: Message, state: FSMContext) -> None:
    city = message.text.strip()

    if len(city) < 2:
        await message.answer("Пожалуйста, введите корректное название города.")
        return

    await message.answer("Проверяю город...")

    is_valid, city_data = await validate_city_with_weather_api(city)

    if not is_valid:
        await message.answer(
            f"Город '{city}' не найден.\n\n"
            "Проверьте правильность написания или используйте формат:\n"
            "'Москва' (кириллицей)\n"
            "'Moscow,RU' (англ. + код страны)\n\n"
            "Введите город еще раз:"
        )
        return

    await state.update_data(city=city, city_data=city_data)

    if city_data and 'timezone' in city_data:
        timezone_offset = city_data['timezone']
        hours = timezone_offset // 3600

        timezone_str = f"UTC{'+' if hours >= 0 else ''}{hours}"
        await state.update_data(timezone_str=timezone_str, auto_timezone=True)

        await message.answer(
            f"Город '{city}' найден!\n"
            f"Часовой пояс автоматически определен: {timezone_str}\n\n"
            "4. Хотите ли вы получать ежедневные рекомендации по одежде утром?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Да, хочу", callback_data="enable_dispatch_yes"),
                        InlineKeyboardButton(text="Нет, не нужно", callback_data="enable_dispatch_no")
                    ]
                ]
            )
        )
    else:
        await state.update_data(auto_timezone=False)
        await message.answer(
            f"Город '{city}' найден!\n\n"
            "4. Хотите ли вы получать ежедневные рекомендации по одежде утром?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Да, хочу", callback_data="enable_dispatch_yes"),
                        InlineKeyboardButton(text="Нет, не нужно", callback_data="enable_dispatch_no")
                    ]
                ]
            )
        )

    await state.set_state(Survey.enable_dispatch)


@dp.callback_query(F.data == "enable_dispatch_yes")
async def process_dispatch_yes(callback: CallbackQuery, state: FSMContext):
    try:
        await state.update_data(enable_dispatch=True)

        data = await state.get_data()
        timezone_str = data.get('timezone_str', 'UTC+3')  # По умолчанию

        await callback.message.edit_text(
            f"Ежедневная рассылка включена.\n"
            f"Часовой пояс: {timezone_str}\n\n"
            "Укажите время утренней рассылки в формате ЧЧ:ММ.\n"
            "Например: 08:00 или 09:30"
        )
        await state.set_state(Survey.local_time)

    except Exception as e:
        logging.error(f"Error in process_dispatch_yes: {e}")

    await callback.answer()


@dp.callback_query(F.data == "enable_dispatch_no")
async def process_dispatch_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(enable_dispatch=False)

    await callback.message.edit_text("Ежедневная рассылка отключена.")
    await ask_style_choice(callback.message, state)
    await callback.answer()


@dp.message(Survey.local_time)
async def process_local_time(message: Message, state: FSMContext) -> None:
    time_str = message.text.strip()

    try:
        hours, minutes = map(int, time_str.split(":"))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError

        formatted_time = f"{hours:02d}:{minutes:02d}"

    except ValueError:
        await message.answer(
            "Неверный формат времени.\n"
            "Используйте ЧЧ:ММ (например, 08:30)\n\n"
            "Попробуйте еще раз:"
        )
        return

    await state.update_data(dispatch_time=formatted_time)

    data = await state.get_data()
    timezone_str = data.get('timezone_str', 'не определен')

    await message.answer(
        f"Время рассылки установлено на {formatted_time}\n"
        f"Часовой пояс: {timezone_str}\n\n"
        "Переходим к выбору стиля одежды..."
    )

    await ask_style_choice(message, state)


async def ask_style_choice(message: Message, state: FSMContext):
    await message.answer(
        "5. Выберите ваш стиль одежды:",
        reply_markup=get_style_choice_keyboard()
    )
    await state.set_state(Survey.clothes_style)


@dp.callback_query(F.data.startswith("style_"), Survey.clothes_style)
async def process_style_choice(callback: CallbackQuery, state: FSMContext):
    try:
        style_key = callback.data.replace("style_", "")

        if style_key not in STYLE_TO_NUMBER:
            await callback.answer("Некорректный стиль")
            return

        style_num = STYLE_TO_NUMBER[style_key]
        style_name = STYLE_NAMES[style_key]

        await state.update_data(clothes_style=style_num)
        await callback.message.edit_text(f"Выбран стиль: {style_name}")
        await finish_survey_for_user(callback, state)

    except Exception as e:
        logging.error(f"Error in process_style_choice: {e}")
        await callback.answer("Ошибка выбора стиля")

    await callback.answer()


async def finish_survey_for_user(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if not data:
        await callback.message.answer("Ошибка: данные опроса не найдены")
        await state.clear()
        return

    user_telegram_id = callback.from_user.id
    user_first_name = callback.from_user.first_name or ""
    user_username = callback.from_user.username or ""

    session: AsyncSession = None

    try:
        session = AsyncSessionLocal()

        stmt = select(User).where(User.telegram_id == user_telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=user_telegram_id,
                username=user_username,
                first_name=user_first_name,
                created_at=datetime.now()
            )
            session.add(user)

        await session.flush()

        name = str(data.get("name", ""))[:100]
        city = str(data.get("city", ""))[:100]
        clothes_style = int(data.get("clothes_style", 1))

        gender_val = data.get("gender")
        if isinstance(gender_val, Gender):
            gender_enum = gender_val
        else:
            gender_str = str(gender_val).upper()
            gender_enum = Gender.MALE if gender_str == "MALE" else Gender.FEMALE

        wants_dispatch = bool(data.get("enable_dispatch", False))
        timezone_str = data.get('timezone_str') if wants_dispatch else None
        dispatch_time = data.get('dispatch_time') if wants_dispatch else None

        stmt = select(UserPreferences).where(UserPreferences.user_id == user.id)
        result = await session.execute(stmt)
        existing_prefs = result.scalar_one_or_none()

        if existing_prefs:
            await session.delete(existing_prefs)
            await session.flush()

        new_prefs = UserPreferences(
            user_id=user.id,
            name=name,
            gender=gender_enum,
            city=city,
            clothing_style=clothes_style,
            wants_dispatch=wants_dispatch,
            timezone=timezone_str,
            dispatch_time=dispatch_time,
            created_at=datetime.now()
        )
        session.add(new_prefs)

        await session.commit()

        await session.close()
        session = None

    except Exception as e:
        logging.error(f"Error saving survey data: {e}")

        if session:
            await session.rollback()
            await session.close()

        await callback.message.answer(f"Ошибка сохранения: {str(e)[:100]}")
        await state.clear()
        return

    finally:
        if session:
            await session.close()

    style_number = data.get('clothes_style', 1)
    style_name = "Неизвестный"
    for key, num in STYLE_TO_NUMBER.items():
        if num == style_number:
            style_name = STYLE_NAMES[key]
            break

    await callback.message.answer(
        f"Настройка завершена и сохранена!\n"
        f"Имя: {data.get('name', '')}\n"
        f"Город: {data.get('city', '')}\n"
        f"Стиль: {style_name}"
    )


@dp.message(Command("change"))
async def command_change_handler(message: Message, state: FSMContext):
    await message.answer(
        "Что вы хотите изменить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Город", callback_data="change_city")],
                [InlineKeyboardButton(text="Стиль одежды", callback_data="change_style")],
                [InlineKeyboardButton(text="Настройки рассылки", callback_data="change_dispatch")],
            ]
        )
    )

@dp.message(Command("check"))
async def command_check_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    city = str(data.get("city", ""))[:100]
    answer = await main_rec(city)
    await message.answer(answer)


@dp.message(Command("settings"))
async def command_settings_handler(message: Message):
    try:
        async for session in get_db():
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                await message.answer("Вы еще не проходили опрос.\nИспользуйте /start")
                return

            prefs_result = await session.execute(
                select(UserPreferences).where(UserPreferences.user_id == user.id)
            )
            prefs = prefs_result.scalar_one_or_none()

            if not prefs:
                await message.answer("Настройки не найдены.\nИспользуйте /start")
                return

            style_number = prefs.clothing_style
            style_name = "Неизвестный"
            for key, num in STYLE_TO_NUMBER.items():
                if num == style_number:
                    style_name = STYLE_NAMES[key]
                    break

            response = (
                f"Ваши текущие настройки:\n\n"
                f"Имя: {prefs.name}\n"
                f"Пол: {'Мужской' if prefs.gender == Gender.MALE else 'Женский'}\n"
                f"Город: {prefs.city}\n"
                f"Стиль: {style_name}\n"  # Теперь показывает название, а не номер
                f"Рассылка: {'Включена' if prefs.wants_dispatch else 'Отключена'}\n"
            )

            if prefs.wants_dispatch:
                if prefs.timezone:
                    response += f"Часовой пояс: {prefs.timezone}\n"
                if prefs.dispatch_time:
                    response += f"Время рассылки: {prefs.dispatch_time}"

            await message.answer(response)

    except Exception as e:
        logging.error(f"Error in /check: {e}")
        await message.answer("Произошла ошибка при проверке данных")


@dp.message(Command("debug"))
async def command_debug_handler(message: Message, state: FSMContext):
    fsm_data = await state.get_data()
    fsm_state = await state.get_state()

    response = (
        f"Отладочная информация:\n\n"
        f"FSM состояние: {fsm_state}\n"
        f"FSM данные: {fsm_data}\n\n"
    )

    try:
        async for session in get_db():
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if user:
                response += f"Пользователь в БД:\n"
                response += f"ID: {user.id}\n"
                response += f"Telegram ID: {user.telegram_id}\n"
                response += f"Username: {user.username}\n"

                prefs_result = await session.execute(
                    select(UserPreferences).where(UserPreferences.user_id == user.id)
                )
                prefs = prefs_result.scalar_one_or_none()

                if prefs:
                    response += f"\nНастройки в БД:\n"
                    response += f"Имя: {prefs.name}\n"
                    response += f"Город: {prefs.city}\n"
                    response += f"Стиль: {prefs.clothing_style}\n"
                    response += f"Рассылка: {prefs.wants_dispatch}\n"
                else:
                    response += f"\nНастройки в БД не найдены"
            else:
                response += f"Пользователь не найден в БД"

    except Exception as e:
        response += f"\nОшибка БД: {str(e)[:100]}"

    await message.answer(response[:4000])


@dp.callback_query(F.data == "change_city")
async def change_city_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите новый город:")
    await state.set_state(Survey.city)
    await callback.answer()


@dp.callback_query(F.data == "change_style")
async def change_style_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите новый стиль одежды:")
    await ask_style_choice(callback.message, state)
    await callback.answer()


@dp.callback_query(F.data == "change_dispatch")
async def change_dispatch_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Хотите ли вы получать ежедневные рекомендации?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Да", callback_data="enable_dispatch_yes"),
                    InlineKeyboardButton(text="Нет", callback_data="enable_dispatch_no")
                ]
            ]
        )
    )
    await callback.answer()


@dp.update.middleware()
async def database_middleware(handler, event, data):
    async for session in get_db():
        data["db"] = session
        return await handler(event, data)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )

    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        pass
    finally:
        await close_db()


@dp.message(Command("state"))
async def command_state_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    current_data = await state.get_data()

    await message.answer(
        f"Текущее состояние:\n"
        f"Состояние: {current_state}\n"
        f"Данные: {current_data}"
    )


if __name__ == "__main__":
    asyncio.run(main())