import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from wardrobe_app.database.connection import get_db
from wardrobe_app.database.models import User, UserPreferences
from wardrobe_app.services.cache import weather_cache
from wardrobe_app.services.weather import WeatherData
from wardrobe_app.services.recommendation import get_clothing_recommendation

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

    def _parse_timezone(self, tz_string: str) -> float:
        try:
            tz_string = tz_string.upper().replace("UTC", "").strip("+")
            if ":" in tz_string:
                hours, minutes = map(int, tz_string.split(":"))
                return hours + (minutes / 60.0 if minutes else 0)
            else:
                return float(tz_string)
        except Exception:
            return 0.0

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
                    grouped.setdefault(city, []).append(user)

        return grouped

    async def _send_notifications(self, grouped_users: Dict[str, List[User]]) -> Dict[str, int]:
        results = {"success": 0, "failed": 0}

        for city, users in grouped_users.items():
            try:
                weather_data = await weather_cache.get_weather(city)

                for user in users:
                    try:
                        async with get_db() as session:
                            prefs_result = await session.execute(
                                "SELECT name, gender, clothing_style FROM user_preferences WHERE user_id = :user_id",
                                {"user_id": user.id}
                            )
                            prefs = prefs_result.fetchone()

                        name = prefs.name if prefs and prefs.name else "Друг"
                        gender = prefs.gender.value if prefs and prefs.gender else "male"
                        style = prefs.clothing_style if prefs and prefs.clothing_style is not None else 0

                        recommendation_text = get_clothing_recommendation(
                            temperature=weather_data.temperature,
                            conditions=weather_data.conditions,
                            gender=gender,
                            style=style
                        )

                        await self._send_user_notification(
                            user=user,
                            city=city,
                            weather=weather_data,
                            recommendation=recommendation_text,
                            name=name
                        )

                        results["success"] += 1
                        await asyncio.sleep(0.05)

                    except TelegramForbiddenError:
                        results["failed"] += 1
                        logger.warning(f"User {user.telegram_id} blocked the bot")
                    except TelegramBadRequest as e:
                        logger.error(f"Telegram error for {user.telegram_id}: {e}")
                        results["failed"] += 1
                    except Exception as e:
                        logger.error(f"Send error for user {user.telegram_id}: {e}")
                        results["failed"] += 1

                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"City processing error {city}: {e}")
                results["failed"] += len(users)

        return results

    async def _send_user_notification(self, user: User, city: str,
                                      weather: WeatherData, recommendation: str, name: str):

        message = (
            f"Доброе утро, {name}!\n\n"
            f"Погода в {city} сегодня:\n"
            f"Температура: {weather.temperature:.1f}°C (ощущается как {weather.feels_like:.1f}°C)\n"
            f"Условия: {weather.conditions}\n"
            f"Влажность: {weather.humidity}%\n"
            f"Ветер: {weather.wind_speed} км/ч\n\n"
            f"Рекомендация по одежде:\n{recommendation}\n"
            f"Хорошего дня! 🌤️"
        )

        await self.bot.send_message(
            chat_id=user.telegram_id,
            text=message,
            parse_mode="HTML"
        )

    def _update_stats(self, results: Dict[str, int], start_time: datetime):
        self.stats["total_sent"] += results["success"]
        self.stats["total_failed"] += results["failed"]
        self.stats["last_success"] = start_time
        self.stats["cities_processed"] += len(results)

    async def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "cache_stats": await weather_cache.get_cache_stats()
        }


async def run_morning_dispatch(bot: Bot):
    dispatcher = MorningDispatcher(bot)
    return await dispatcher.run_dispatch()