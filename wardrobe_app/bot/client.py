import aiohttp
import asyncio
import logging
import sys
import re
from datetime import datetime, time, date
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext

from wardrobe_app.database.connection import get_db, init_db, close_db
from wardrobe_app.database.crud import UserCRUD, PreferencesCRUD
from wardrobe_app.database.models import Gender
from wardrobe_app.bot.keyboards import get_style_choice_keyboard
from wardrobe_app.config import settings

from sqlalchemy import select
from wardrobe_app.database.models import User, UserPreferences


# ===== ВАЛИДАЦИЯ ГОРОДА =====
async def validate_city_with_weather_api(city_name: str) -> bool:
    """
    Проверяет существование города через OpenWeatherMap Geocoding API.
    Пока заглушка - всегда возвращает True.
    """
    # TODO: Раскомментируйте когда добавите WEATHERAPI_KEY в settings
    """
    if not settings.WEATHERAPI_KEY:
        return True

    url = "http://api.openweathermap.org/geo/1.0/direct"
    params = {
        "q": city_name,
        "limit": 1,
        "appid": settings.WEATHERAPI_KEY
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return isinstance(data, list) and len(data) > 0
                return False
    except Exception:
        return True  # При ошибке сети пропускаем проверку
    """
    return True  # Заглушка для тестирования


# ===== СОСТОЯНИЯ FSM =====
class Survey(StatesGroup):
    name = State()
    gender = State()
    city = State()
    enable_dispatch = State()
    timezone = State()
    local_time = State()
    clothes_style = State()


# ===== ИНИЦИАЛИЗАЦИЯ =====
dp = Dispatcher(storage=MemoryStorage())


# ===== КОМАНДА /start =====
@dp.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext) -> None:
    """Начало опроса"""
    await state.clear()
    print(f"🔍 [DEBUG] /start от {message.from_user.id}")

    await message.answer(
        "👕 Добро пожаловать в Гардеробный бот!\n"
        "Я помогу вам подобрать одежду по погоде.\n\n"
        "Давайте пройдем короткий опрос для настройки.\n\n"
        "1. Как вас зовут?"
    )
    await state.set_state(Survey.name)


# ===== ОБРАБОТКА ИМЕНИ =====
@dp.message(Survey.name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Шаг 1: Получаем имя"""
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите имя (минимум 2 символа).")
        return

    await state.update_data(name=name)
    print(f"🔍 [DEBUG] Сохранено имя: {name}")

    await message.answer(
        f"Приятно познакомиться, {name}!\n\n"
        "2. Укажите ваш пол для более точных рекомендаций:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👨 Мужской", callback_data="gender_male")],
                [InlineKeyboardButton(text="👩 Женский", callback_data="gender_female")]
            ]
        )
    )
    await state.set_state(Survey.gender)


# ===== ОБРАБОТКА ПОЛА =====
@dp.callback_query(F.data.startswith("gender_"))
async def process_gender(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: Обработка выбора пола"""
    gender_map = {
        "gender_male": Gender.MALE,
        "gender_female": Gender.FEMALE
    }

    selected = gender_map.get(callback.data)
    if not selected:
        await callback.answer("Ошибка выбора пола")
        return

    await state.update_data(gender=selected)
    print(f"🔍 [DEBUG] Сохранен пол: {selected}")

    await callback.message.edit_text(
        f"✅ Пол выбран: {'Мужской' if selected == Gender.MALE else 'Женский'}"
    )

    await callback.message.answer(
        "3. В каком городе вы живете?\n"
        "Например: Москва, Санкт-Петербург, London"
    )
    await state.set_state(Survey.city)
    await callback.answer()


# ===== ОБРАБОТКА ГОРОДА =====
@dp.message(Survey.city)
async def process_city(message: Message, state: FSMContext) -> None:
    """Шаг 3: Получаем и проверяем город"""
    city = message.text.strip()

    if len(city) < 2:
        await message.answer("Пожалуйста, введите корректное название города.")
        return

    await message.answer("🔍 Проверяю город...")

    # Валидация города (пока заглушка)
    is_valid = await validate_city_with_weather_api(city)

    if not is_valid:
        await message.answer(
            f"❌ Город '{city}' не найден.\n\n"
            "Проверьте правильность написания или используйте формат:\n"
            "• 'Москва' (кириллицей)\n"
            "• 'Moscow,RU' (англ. + код страны)\n"
            "• 'London,UK'\n\n"
            "Введите город еще раз:"
        )
        return

    await state.update_data(city=city)
    print(f"🔍 [DEBUG] Сохранен город: {city}")

    await message.answer(
        f"✅ Город '{city}' найден!\n\n"
        "4. Хотите ли вы получать ежедневные рекомендации по одежде утром?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, хочу", callback_data="enable_dispatch_yes"),
                    InlineKeyboardButton(text="❌ Нет, не нужно", callback_data="enable_dispatch_no")
                ]
            ]
        )
    )
    await state.set_state(Survey.enable_dispatch)


# ===== ОБРАБОТКА РАССЫЛКИ =====
@dp.callback_query(F.data == "enable_dispatch_yes")
async def process_dispatch_yes(callback: CallbackQuery, state: FSMContext):
    """Шаг 4а: Пользователь хочет рассылку"""
    try:
        # Обновляем состояние
        await state.update_data(enable_dispatch=True)
        print(f"🔍 [DEBUG] Рассылка: ВКЛЮЧЕНА")

        # Получаем текущие данные для отладки
        current_data = await state.get_data()
        print(f"🔍 [DEBUG] Текущие данные после enable_dispatch: {current_data}")

        # Отправляем сообщение и устанавливаем новое состояние
        await callback.message.edit_text(
            "✅ Ежедневная рассылка включена.\n\n"
            "Укажите ваш часовой пояс относительно UTC.\n"
            "Примеры:\n"
            "• UTC+3 (для Москвы)\n"
            "• UTC+5 (для Екатеринбурга)\n"
            "• UTC-5 (для Нью-Йорка)"
        )

        # Устанавливаем состояние ДО ответа
        await state.set_state(Survey.timezone)

        print(f"🔍 [DEBUG] Состояние установлено: {await state.get_state()}")

    except Exception as e:
        print(f"❌ [DEBUG] Ошибка в process_dispatch_yes: {e}")
        import traceback
        traceback.print_exc()

    await callback.answer()


@dp.callback_query(F.data == "enable_dispatch_no")
async def process_dispatch_no(callback: CallbackQuery, state: FSMContext):
    """Шаг 4б: Пользователь НЕ хочет рассылку"""
    await state.update_data(enable_dispatch=False)
    print(f"🔍 [DEBUG] Рассылка: ОТКЛЮЧЕНА")

    await callback.message.edit_text("✅ Ежедневная рассылка отключена.")
    await ask_style_choice(callback.message, state)
    await callback.answer()


# ===== ОБРАБОТКА ЧАСОВОГО ПОЯСА =====
@dp.message(Survey.timezone)
async def process_timezone(message: Message, state: FSMContext) -> None:
    """Шаг 5: Получаем часовой пояс (только если включена рассылка)"""
    timezone_str = message.text.strip().upper()

    # Простая валидация формата
    pattern = r"^UTC[+-]\d{1,2}(:\d{2})?$"
    if not re.match(pattern, timezone_str):
        await message.answer(
            "Неверный формат часового пояса.\n"
            "Используйте формат: UTC+3 или UTC-5\n\n"
            "Попробуйте еще раз:"
        )
        return

    await state.update_data(timezone_str=timezone_str)
    print(f"🔍 [DEBUG] Сохранен часовой пояс: {timezone_str}")

    await message.answer(
        f"Часовой пояс '{timezone_str}' сохранен.\n\n"
        "Введите время утренней рассылки в формате ЧЧ:ММ.\n"
        "Например: 08:00 или 09:30"
    )
    await state.set_state(Survey.local_time)


# ===== ОБРАБОТКА ВРЕМЕНИ РАССЫЛКИ =====
@dp.message(Survey.local_time)
async def process_local_time(message: Message, state: FSMContext) -> None:
    """Шаг 6: Получаем время рассылки"""
    time_str = message.text.strip()

    # Проверяем формат ЧЧ:ММ
    try:
        hours, minutes = map(int, time_str.split(":"))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError

        # Форматируем обратно
        formatted_time = f"{hours:02d}:{minutes:02d}"

    except ValueError:
        await message.answer(
            "Неверный формат времени.\n"
            "Используйте ЧЧ:ММ (например, 08:30)\n\n"
            "Попробуйте еще раз:"
        )
        return

    await state.update_data(dispatch_time=formatted_time)
    print(f"🔍 [DEBUG] Сохранено время рассылки: {formatted_time}")

    await message.answer(f"⏰ Время рассылки установлено на {formatted_time}.")
    await ask_style_choice(message, state)


# ===== ВЫБОР СТИЛЯ =====
async def ask_style_choice(message: Message, state: FSMContext):
    """Шаг 7: Показываем выбор стиля"""
    await message.answer(
        "5. Выберите ваш стиль одежды (от 1 до 10):\n"
        "1 - Классический 👔\n"
        "2 - Спортивный 🏃\n"
        "3 - Повседневный 👕\n"
        "4 - Деловой 💼\n"
        "5 - Минимализм ⚫\n"
        "6 - Уличный стиль 🛹\n"
        "7 - Элегантный 🎩\n"
        "8 - Романтический 💝\n"
        "9 - Бохо 🌸\n"
        "10 - Экспериментальный 🎨",
        reply_markup=get_style_choice_keyboard()
    )
    await state.set_state(Survey.clothes_style)


@dp.callback_query(F.data.startswith("style_"), Survey.clothes_style)
async def process_style_choice(callback: CallbackQuery, state: FSMContext):
    """Шаг 7: Обработка выбора стиля"""
    print(f"🔍 [DEBUG] Нажата кнопка стиля: {callback.data}")

    try:
        # Извлекаем номер стиля из callback_data
        style_num = int(callback.data.replace("style_", ""))

        if not (1 <= style_num <= 10):
            await callback.answer("Некорректный номер стиля")
            return

        # Сохраняем стиль в FSM
        await state.update_data(clothes_style=style_num)

        # Получаем ВСЕ данные из FSM для отладки
        all_data = await state.get_data()
        print(f"🔍 [DEBUG] Все данные в FSM перед сохранением: {all_data}")

        # Редактируем сообщение
        await callback.message.edit_text(f"✅ Выбран стиль №{style_num}")

        # Завершаем опрос и сохраняем в БД
        await finish_survey(callback.message, state)

    except ValueError as e:
        print(f"❌ [DEBUG] Ошибка обработки стиля: {e}")
        await callback.answer("Ошибка выбора стиля")
        return
    except Exception as e:
        print(f"❌ [DEBUG] Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        await callback.answer("Произошла ошибка")
        return

    await callback.answer()


# ===== СОХРАНЕНИЕ В БАЗУ ДАННЫХ =====
async def finish_survey(message: Message, state: FSMContext):
    """Финальный шаг: Сохраняем все данные в БД"""
    print("=" * 50)
    print("🔍 [DEBUG] НАЧАЛО finish_survey")

    data = await state.get_data()
    print(f"🔍 [DEBUG] Данные из FSM: {data}")

    if not data:
        await message.answer("❌ Ошибка: данные опроса не найдены")
        await state.clear()
        return

    # Импортируем здесь чтобы избежать циклических импортов
    from wardrobe_app.database.connection import AsyncSessionLocal

    session = None
    try:
        # СОЗДАЕМ сессию вручную
        session = AsyncSessionLocal()

        # 1. ПОЛЬЗОВАТЕЛЬ
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "",
                created_at=datetime.now()
            )
            session.add(user)
            await session.flush()
            print(f"✅ Создан пользователь ID={user.id}")
        else:
            print(f"✅ Найден пользователь ID={user.id}")

        # 2. ПРЕДПОЧТЕНИЯ
        # Преобразуем gender
        gender_value = data.get("gender")
        gender_enum = Gender.MALE if str(gender_value).upper() == "MALE" else Gender.FEMALE

        # Настройки рассылки
        wants_dispatch = data.get("enable_dispatch", False)
        timezone_str = data.get("timezone_str") if wants_dispatch else None
        dispatch_time = data.get("dispatch_time") if wants_dispatch else None

        # Ищем существующие настройки
        prefs_result = await session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        prefs = prefs_result.scalar_one_or_none()

        if prefs:
            # Обновляем существующие
            prefs.name = str(data.get("name", ""))[:100]
            prefs.gender = gender_enum
            prefs.city = str(data.get("city", ""))[:100]
            prefs.clothing_style = int(data.get("clothes_style", 1))
            prefs.wants_dispatch = bool(wants_dispatch)
            prefs.timezone = timezone_str
            prefs.dispatch_time = dispatch_time
            prefs.created_at = datetime.now()
            print(f"🔄 Обновлены настройки для user_id={user.id}")
        else:
            # Создаем новые
            prefs = UserPreferences(
                user_id=user.id,
                name=str(data.get("name", ""))[:100],
                gender=gender_enum,
                city=str(data.get("city", ""))[:100],
                clothing_style=int(data.get("clothes_style", 1)),
                wants_dispatch=bool(wants_dispatch),
                timezone=timezone_str,
                dispatch_time=dispatch_time,
                created_at=datetime.now()
            )
            session.add(prefs)
            print(f"➕ Созданы новые настройки для user_id={user.id}")

        # ВАЖНО: ЯВНЫЙ КОММИТ
        await session.commit()
        print(f"✅ [КОММИТ] Данные сохранены в БД! user_id={user.id}")

        # ПРОВЕРКА ПОСЛЕ КОММИТА
        check_result = await session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user.id)
        )
        saved_prefs = check_result.scalar_one()

        print(f"✅ [ПРОВЕРКА] Данные в БД:")
        print(f"  • ID: {saved_prefs.id}")
        print(f"  • Имя: {saved_prefs.name}")
        print(f"  • Город: {saved_prefs.city}")
        print(f"  • Стиль: {saved_prefs.clothing_style}")

        # Очищаем сессию
        await session.close()

    except Exception as e:
        print(f"❌ [ОШИБКА] При сохранении: {e}")
        import traceback
        traceback.print_exc()

        # Если сессия открыта - откатываем
        if session:
            await session.rollback()
            await session.close()

        await message.answer(f"❌ Ошибка сохранения: {str(e)[:100]}")
        return

    finally:
        # Гарантируем закрытие сессии
        if session:
            await session.close()

    # Итоговое сообщение
    await message.answer(
        f"🎉 Настройка завершена!\n"
        f"• Имя: {data.get('name', '')}\n"
        f"• Город: {data.get('city', '')}\n"
        f"• Стиль: №{data.get('clothes_style', 1)}"
    )

    await state.clear()
    print("✅ FSM очищен")

    # ===== 5. ИТОГОВОЕ СООБЩЕНИЕ =====
    city = data.get('city', 'не указан')
    style = data.get('clothes_style', 1)
    name = data.get('name', '')

    response_text = (
        f"🎉 Настройка завершена и успешно сохранена!\n\n"
        f"📋 Ваши данные:\n"
        f"• Имя: {name}\n"
        f"• Город: {city}\n"
        f"• Стиль одежды: №{style}\n"
    )

    if data.get('enable_dispatch'):
        response_text += f"• Ежедневная рассылка: ✅ Включена\n"
        response_text += f"• Время: {data.get('dispatch_time', 'не указано')}\n"
        response_text += f"• Часовой пояс: {data.get('timezone_str', 'не указан')}"
    else:
        response_text += "• Ежедневная рассылка: ❌ Отключена"

    await message.answer(response_text)

    # Очищаем состояние
    await state.clear()
    print("✅ [DEBUG] Состояние FSM очищено")

    # ===== 5. ИТОГОВОЕ СООБЩЕНИЕ =====
    city = data.get('city', 'не указан')
    style = data.get('clothes_style', 1)
    name = data.get('name', '')

    response_text = (
        f"🎉 Настройка завершена и успешно сохранена!\n\n"
        f"📋 Ваши данные:\n"
        f"• Имя: {name}\n"
        f"• Город: {city}\n"
        f"• Стиль одежды: №{style}\n"
    )

    if data.get('enable_dispatch'):
        response_text += f"• Ежедневная рассылка: ✅ Включена\n"
        response_text += f"• Время: {data.get('dispatch_time', 'не указано')}\n"
        response_text += f"• Часовой пояс: {data.get('timezone_str', 'не указан')}"
    else:
        response_text += "• Ежедневная рассылка: ❌ Отключена"

    await message.answer(response_text)

    # Очищаем состояние
    await state.clear()
    print("✅ [DEBUG] Состояние FSM очищено")


# ===== КОМАНДА /change =====
@dp.message(Command("change"))
async def command_change_handler(message: Message, state: FSMContext):
    """Изменение настроек"""
    await message.answer(
        "Что вы хотите изменить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏙️ Город", callback_data="change_city")],
                [InlineKeyboardButton(text="👕 Стиль одежды", callback_data="change_style")],
                [InlineKeyboardButton(text="⏰ Настройки рассылки", callback_data="change_dispatch")],
            ]
        )
    )


# ===== КОМАНДА /check =====
@dp.message(Command("check"))
async def command_check_handler(message: Message):
    """Проверка сохраненных данных"""
    try:
        async for session in get_db():
            # Ищем пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                await message.answer("❌ Вы еще не проходили опрос.\nИспользуйте /start")
                return

            # Ищем настройки
            prefs_result = await session.execute(
                select(UserPreferences).where(UserPreferences.user_id == user.id)
            )
            prefs = prefs_result.scalar_one_or_none()

            if not prefs:
                await message.answer("❌ Настройки не найдены.\nИспользуйте /start")
                return

            # Формируем ответ
            response = (
                f"✅ Ваши текущие настройки:\n\n"
                f"👤 Имя: {prefs.name}\n"
                f"⚧ Пол: {'Мужской' if prefs.gender == Gender.MALE else 'Женский'}\n"
                f"🏙️ Город: {prefs.city}\n"
                f"👕 Стиль: №{prefs.clothing_style}\n"
                f"📅 Рассылка: {'✅ Включена' if prefs.wants_dispatch else '❌ Отключена'}\n"
            )

            if prefs.wants_dispatch:
                if prefs.timezone:
                    response += f"🌍 Часовой пояс: {prefs.timezone}\n"
                if prefs.dispatch_time:
                    response += f"⏰ Время рассылки: {prefs.dispatch_time}"

            await message.answer(response)

    except Exception as e:
        print(f"❌ Ошибка в /check: {e}")
        await message.answer("⚠️ Произошла ошибка при проверке данных")


# ===== КОМАНДА /debug =====
@dp.message(Command("debug"))
async def command_debug_handler(message: Message, state: FSMContext):
    """Отладочная команда - показывает данные FSM и БД"""
    # Данные FSM
    fsm_data = await state.get_data()
    fsm_state = await state.get_state()

    response = (
        f"🔍 ОТЛАДОЧНАЯ ИНФОРМАЦИЯ:\n\n"
        f"📊 FSM состояние: {fsm_state}\n"
        f"📊 FSM данные: {fsm_data}\n\n"
    )

    # Данные из БД
    try:
        async for session in get_db():
            user_result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if user:
                response += f"👤 Пользователь в БД:\n"
                response += f"  • ID: {user.id}\n"
                response += f"  • Telegram ID: {user.telegram_id}\n"
                response += f"  • Username: {user.username}\n"

                prefs_result = await session.execute(
                    select(UserPreferences).where(UserPreferences.user_id == user.id)
                )
                prefs = prefs_result.scalar_one_or_none()

                if prefs:
                    response += f"\n⚙️ Настройки в БД:\n"
                    response += f"  • Имя: {prefs.name}\n"
                    response += f"  • Город: {prefs.city}\n"
                    response += f"  • Стиль: {prefs.clothing_style}\n"
                    response += f"  • Рассылка: {prefs.wants_dispatch}\n"
                else:
                    response += f"\n❌ Настройки в БД не найдены"
            else:
                response += f"❌ Пользователь не найден в БД"

    except Exception as e:
        response += f"\n❌ Ошибка БД: {str(e)[:100]}"

    await message.answer(response[:4000])  # Ограничение Telegram


# ===== ОБРАБОТЧИКИ ИЗМЕНЕНИЯ НАСТРОЕК =====
@dp.callback_query(F.data == "change_city")
async def change_city_handler(callback: CallbackQuery, state: FSMContext):
    """Изменение города"""
    await callback.message.edit_text("Введите новый город:")
    await state.set_state(Survey.city)
    await callback.answer()


@dp.callback_query(F.data == "change_style")
async def change_style_handler(callback: CallbackQuery, state: FSMContext):
    """Изменение стиля"""
    await callback.message.edit_text("Выберите новый стиль одежды:")
    await ask_style_choice(callback.message, state)
    await callback.answer()


@dp.callback_query(F.data == "change_dispatch")
async def change_dispatch_handler(callback: CallbackQuery, state: FSMContext):
    """Изменение настроек рассылки"""
    await callback.message.edit_text(
        "Хотите ли вы получать ежедневные рекомендации?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да", callback_data="enable_dispatch_yes"),
                    InlineKeyboardButton(text="❌ Нет", callback_data="enable_dispatch_no")
                ]
            ]
        )
    )
    await callback.answer()


# ===== MIDDLEWARE ДЛЯ БД =====
@dp.update.middleware()
async def database_middleware(handler, event, data):
    """Middleware для передачи сессии БД в обработчики"""
    async for session in get_db():
        data["db"] = session
        return await handler(event, data)


# ===== ЗАПУСК БОТА =====
async def main() -> None:
    """Основная функция запуска бота"""
    print("🚀 Инициализация бота...")
    print(f"🔑 Токен бота: {'установлен' if settings.BOT_TOKEN else 'НЕ НАЙДЕН!'}")

    # Инициализация базы данных
    print("💾 Инициализация базы данных...")
    await init_db()
    print("✅ База данных готова")

    # Создание бота
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Запуск бота
    print("🤖 Бот запущен. Ожидание сообщений...")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n👋 Остановка бота...")
    finally:
        await close_db()
        print("✅ Ресурсы освобождены")


@dp.message(Command("state"))
async def command_state_handler(message: Message, state: FSMContext):
    """Показать текущее состояние FSM"""
    current_state = await state.get_state()
    current_data = await state.get_data()

    await message.answer(
        f"🔍 ТЕКУЩЕЕ СОСТОЯНИЕ:\n"
        f"• Состояние: {current_state}\n"
        f"• Данные: {current_data}\n"
        f"• Класс Survey: {Survey}"
    )

if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )

    # Запуск асинхронного приложения
    asyncio.run(main())