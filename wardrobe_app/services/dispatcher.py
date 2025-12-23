import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from wardrobe_app.database.connection import get_db
from wardrobe_app.database.models import User, UserPreferences
from wardrobe_app.database.crud import UserCRUD, PreferencesCRUD
from .cache import weather_cache
from . import recommendation
from .weather import WeatherData

logger = logging.getLogger(__name__)


class MorningDispatcher:
    """Система утренней рассылки рекомендаций"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.last_run: Optional[datetime] = None
        self.stats = {
            "total_sent": 0,
            "total_failed": 0,
            "last_success": None,
            "cities_processed": 0
        }

    async def run_dispatch(self) -> Dict[str, Any]:
        """
        Основной метод рассылки.
        Вызывается планировщиком каждые 60 минут.

        Returns:
            Статистика выполнения
        """
        logger.info("🚀 Запуск утренней рассылки...")
        start_time = datetime.now()

        try:
            # Получаем пользователей для рассылки
            users_to_notify = await self._get_users_for_dispatch()

            if not users_to_notify:
                logger.info("Нет пользователей для рассылки в это время")
                return {"status": "no_users", "count": 0}

            # Группируем по городам для эффективного кэширования
            grouped_by_city = await self._group_users_by_city(users_to_notify)

            # Отправляем сообщения
            results = await self._send_notifications(grouped_by_city)

            # Обновляем статистику
            self._update_stats(results, start_time)

            logger.info(f"✅ Рассылка завершена. Отправлено: {results['success']}, Ошибок: {results['failed']}")
            return {
                "status": "success",
                "sent": results["success"],
                "failed": results["failed"],
                "duration_seconds": (datetime.now() - start_time).total_seconds()
            }

        except Exception as e:
            logger.error(f"❌ Критическая ошибка рассылки: {e}")
            return {"status": "error", "error": str(e)}

    async def _get_users_for_dispatch(self) -> List[User]:
        """
        Получает пользователей, которым нужно отправить рассылку СЕЙЧАС.
        Учитывает timezone и dispatch_time.
        """
        now_utc = datetime.now(timezone.utc)
        current_hour_utc = now_utc.hour

        users_for_dispatch = []

        async with get_db() as session:
            # Получаем пользователей с включенной рассылкой
            result = await session.execute("""
                SELECT u.* FROM users u
                JOIN user_preferences p ON u.id = p.user_id
                WHERE p.wants_dispatch = 1
                AND p.dispatch_time IS NOT NULL
                AND p.timezone IS NOT NULL
            """)

            users = result.fetchall()

            for user in users:
                try:
                    # Получаем настройки пользователя
                    prefs_result = await session.execute(
                        "SELECT * FROM user_preferences WHERE user_id = :user_id",
                        {"user_id": user.id}
                    )
                    prefs = prefs_result.fetchone()

                    if not prefs:
                        continue

                    # Парсим время рассылки
                    dispatch_hour, dispatch_minute = map(int, prefs.dispatch_time.split(":"))

                    # Парсим часовой пояс (например, "UTC+3")
                    tz_offset = self._parse_timezone(prefs.timezone)

                    # Вычисляем текущий час в часовом поясе пользователя
                    user_time = now_utc + timedelta(hours=tz_offset)
                    user_hour = user_time.hour

                    # Если сейчас час рассылки у пользователя (+/- 1 час для надежности)
                    if dispatch_hour - 1 <= user_hour <= dispatch_hour + 1:
                        users_for_dispatch.append(user)

                except Exception as e:
                    logger.error(f"Ошибка обработки пользователя {user.id}: {e}")
                    continue

        logger.info(f"Найдено {len(users_for_dispatch)} пользователей для рассылки")
        return users_for_dispatch

    def _parse_timezone(self, tz_string: str) -> int:
        """Парсит строку часового пояса в смещение в часах"""
        try:
            # Форматы: "UTC+3", "UTC-5", "+03:00"
            tz_string = tz_string.upper().replace("UTC", "")

            if ":" in tz_string:
                hours, minutes = map(int, tz_string.split(":"))
                return hours + (minutes / 60)
            else:
                return int(tz_string)
        except:
            return 0  # По умолчанию UTC

    async def _group_users_by_city(self, users: List[User]) -> Dict[str, List[User]]:
        """Группирует пользователей по городам"""
        grouped = {}

        async with get_db() as session:
            for user in users:
                prefs_result = await session.execute(
                    "SELECT city FROM user_preferences WHERE user_id = :user_id",
                    {"user_id": user.id}
                )
                city_row = prefs_result.fetchone()

                if city_row and city_row.city:
                    city = city_row.city
                    if city not in grouped:
                        grouped[city] = []
                    grouped[city].append(user)

        logger.info(f"Сгруппировано по {len(grouped)} городам")
        return grouped

    async def _send_notifications(self, grouped_users: Dict[str, List[User]]) -> Dict[str, int]:
        """Отправляет уведомления сгруппированным пользователям"""
        results = {"success": 0, "failed": 0}

        for city, users in grouped_users.items():
            try:
                # Получаем погоду для города (с кэшированием)
                weather_data = await weather_cache.get_weather(city)

                # Создаем рекомендацию
                recommendation_text = self._generate_recommendation(weather_data, users[0])

                # Отправляем каждому пользователю
                for user in users:
                    try:
                        await self._send_user_notification(user, city, weather_data, recommendation_text)
                        results["success"] += 1

                        # Небольшая пауза чтобы не спамить Telegram API
                        await asyncio.sleep(0.05)

                    except TelegramForbiddenError:
                        logger.warning(f"Пользователь {user.id} заблокировал бота")
                        results["failed"] += 1
                    except TelegramBadRequest as e:
                        logger.error(f"Ошибка Telegram для {user.id}: {e}")
                        results["failed"] += 1
                    except Exception as e:
                        logger.error(f"Ошибка отправки {user.id}: {e}")
                        results["failed"] += 1

                # Пауза между городами
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Ошибка обработки города {city}: {e}")
                results["failed"] += len(users)

        return results

    def _generate_recommendation(self, weather: WeatherData, user: User) -> str:
        """Генерирует рекомендацию на основе погоды и пользователя"""
        # Здесь будет сложная логика рекомендаций
        # Пока используем простой шаблон

        temperature = weather.temperature
        conditions = weather.conditions.lower()

        # Простая логика рекомендаций
        if temperature > 25:
            temp_advice = "Очень тепло, наденьте легкую одежду"
        elif temperature > 15:
            temp_advice = "Тепло, подойдет демисезонная одежда"
        elif temperature > 5:
            temp_advice = "Прохладно, возьмите куртку"
        else:
            temp_advice = "Холодно, наденьте теплую одежду"

        # Условия
        if "дождь" in conditions or "дожд" in conditions:
            conditions_advice = "Возьмите зонт или дождевик"
        elif "снег" in conditions:
            conditions_advice = "Оденьтесь теплее, возможен снег"
        elif "солн" in conditions or "ясн" in conditions:
            conditions_advice = "Солнечно, не забудьте головной убор"
        else:
            conditions_advice = ""

        return f"{temp_advice}. {conditions_advice}".strip()

    async def _send_user_notification(self, user: User, city: str,
                                      weather: WeatherData, recommendation: str):
        """Отправляет персональное уведомление пользователю"""
        # Получаем имя пользователя
        async with get_db() as session:
            prefs_result = await session.execute(
                "SELECT name FROM user_preferences WHERE user_id = :user_id",
                {"user_id": user.id}
            )
            name_row = prefs_result.fetchone()
            name = name_row.name if name_row else "Пользователь"

        # Формируем сообщение
        emoji = self._get_weather_emoji(weather.conditions)

        message = (
            f"☀️ Доброе утро, {name}!\n\n"
            f"{emoji} Погода в {city} сегодня:\n"
            f"• Температура: {weather.temperature:.1f}°C (ощущается как {weather.feels_like:.1f}°C)\n"
            f"• Условия: {weather.conditions}\n"
            f"• Влажность: {weather.humidity}%\n"
            f"• Ветер: {weather.wind_speed} км/ч\n\n"
            f"👕 Рекомендация по одежде:\n{recommendation}\n\n"
            f"Хорошего дня! 🌟"
        )

        # Отправляем сообщение
        await self.bot.send_message(
            chat_id=user.telegram_id,
            text=message,
            parse_mode="HTML"
        )

        # Логируем успешную отправку
        logger.debug(f"Отправлено уведомление пользователю {user.id} ({city})")

    def _get_weather_emoji(self, conditions: str) -> str:
        """Возвращает эмодзи для погодных условий"""
        conditions_lower = conditions.lower()

        if "солн" in conditions_lower or "ясн" in conditions_lower:
            return "☀️"
        elif "дожд" in conditions_lower:
            return "🌧️"
        elif "снег" in conditions_lower:
            return "❄️"
        elif "облач" in conditions_lower or "пасмур" in conditions_lower:
            return "☁️"
        elif "туман" in conditions_lower:
            return "🌫️"
        elif "гроз" in conditions_lower:
            return "⛈️"
        else:
            return "🌤️"

    def _update_stats(self, results: Dict[str, int], start_time: datetime):
        """Обновляет статистику выполнения"""
        self.stats["total_sent"] += results["success"]
        self.stats["total_failed"] += results["failed"]
        self.stats["last_success"] = start_time

    async def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику диспетчера"""
        return {
            **self.stats,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "cache_stats": await weather_cache.get_cache_stats()
        }


# Утилитарная функция для планировщика
async def run_morning_dispatch(bot: Bot):
    """Функция-обертка для планировщика"""
    dispatcher = MorningDispatcher(bot)
    return await dispatcher.run_dispatch()