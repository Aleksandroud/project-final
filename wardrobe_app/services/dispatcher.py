import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from wardrobe_app.database.connection import get_db
from wardrobe_app.llm_model.model import generate_clothing_recommendation
from wardrobe_app.database.connection import get_db
from wardrobe_app.database.models import User, UserPreferences
from .cache import weather_cache
from .weather import WeatherData
from json import dumps

logger = logging.getLogger(__name__)


class MorningDispatcher:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.last_run = None
        self.stats = {
            "total_sent": 0,
            "total_failed": 0,
            "last_success": None,
            "cities_processed": 0
        }

    async def run_dispatch(self) -> Dict[str, Any]:
        start_time = datetime.now()

        try:
            users_to_notify = await self._get_users_for_dispatch()

            if not users_to_notify:
                return {"status": "no_users", "count": 0}

            grouped_by_city = await self._group_users_by_city(users_to_notify)
            results = await self._send_notifications(grouped_by_city)

            self._update_stats(results, start_time)

            logger.info(f"Dispatch completed. Sent: {results['success']}, Failed: {results['failed']}")
            return {
                "status": "success",
                "sent": results["success"],
                "failed": results["failed"],
                "duration_seconds": (datetime.now() - start_time).total_seconds()
            }

        except Exception as e:
            logger.error(f"Dispatch error: {e}")
            return {"status": "error", "error": str(e)}

    async def _get_users_for_dispatch(self) -> List[User]:
        now_utc = datetime.now(timezone.utc)
        current_hour_utc = now_utc.hour
        users_for_dispatch = []

        async with get_db() as session:
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
                    prefs_result = await session.execute(
                        "SELECT * FROM user_preferences WHERE user_id = :user_id",
                        {"user_id": user.id}
                    )
                    prefs = prefs_result.fetchone()

                    if not prefs:
                        continue

                    dispatch_hour, dispatch_minute = map(int, prefs.dispatch_time.split(":"))
                    tz_offset = self._parse_timezone(prefs.timezone)
                    user_time = now_utc + timedelta(hours=tz_offset)
                    user_hour = user_time.hour

                    if dispatch_hour - 1 <= user_hour <= dispatch_hour + 1:
                        users_for_dispatch.append(user)

                except Exception as e:
                    logger.error(f"User processing error {user.id}: {e}")
                    continue

        return users_for_dispatch

    def _parse_timezone(self, tz_string: str) -> int:
        try:
            tz_string = tz_string.upper().replace("UTC", "")

            if ":" in tz_string:
                hours, minutes = map(int, tz_string.split(":"))
                return hours + (minutes / 60)
            else:
                return int(tz_string)
        except:
            return 0

    async def _group_users_by_city(self, users: List[User]) -> Dict[str, List[User]]:
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

        return grouped

    async def _send_notifications(self, grouped_users: Dict[str, List[User]]) -> Dict[str, int]:
        results = {"success": 0, "failed": 0}

        for city, users in grouped_users.items():
            try:
                weather_data = await weather_cache.get_weather(city)
                recommendation_text = self._generate_recommendation(weather_data, users[0])

                for user in users:
                    try:
                        await self._send_user_notification(user, city, weather_data, recommendation_text)
                        results["success"] += 1
                        await asyncio.sleep(0.05)

                    except TelegramForbiddenError:
                        results["failed"] += 1
                    except TelegramBadRequest as e:
                        logger.error(f"Telegram error for {user.id}: {e}")
                        results["failed"] += 1
                    except Exception as e:
                        logger.error(f"Send error {user.id}: {e}")
                        results["failed"] += 1

                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"City processing error {city}: {e}")
                results["failed"] += len(users)

        return results

    def _generate_recommendation(self, weather: WeatherData, user: User) -> str:
        return generate_clothing_recommendation(user.telegram_id, str(dumps(weather)))

    async def _send_user_notification(self, user: User, city: str,
                                      weather: WeatherData, recommendation: str):
        async with get_db() as session:
            prefs_result = await session.execute(
                "SELECT name FROM user_preferences WHERE user_id = :user_id",
                {"user_id": user.id}
            )
            name_row = prefs_result.fetchone()
            name = name_row.name if name_row else "Пользователь"

        emoji = self._get_weather_emoji(weather.conditions)

        message = (
            f"Доброе утро, {name}!\n\n"
            f"{emoji} Погода в {city} сегодня:\n"
            f"Температура: {weather.temperature:.1f}°C (ощущается как {weather.feels_like:.1f}°C)\n"
            f"Условия: {weather.conditions}\n"
            f"Влажность: {weather.humidity}%\n"
            f"Ветер: {weather.wind_speed} км/ч\n\n"
            f"Рекомендация по одежде:\n{recommendation}\n"
            f"Хорошего дня!"
        )

        await self.bot.send_message(
            chat_id=user.telegram_id,
            text=message,
            parse_mode="HTML"
        )

    def _get_weather_emoji(self, conditions: str) -> str:
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
        self.stats["total_sent"] += results["success"]
        self.stats["total_failed"] += results["failed"]
        self.stats["last_success"] = start_time

    async def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "cache_stats": await weather_cache.get_cache_stats()
        }


async def run_morning_dispatch(bot: Bot):
    dispatcher = MorningDispatcher(bot)
    return await dispatcher.run_dispatch()