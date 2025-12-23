import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import redis.asyncio as aioredis
from wardrobe_app.config import settings
from wardrobe_app.database.connection import get_db
from .weather import WeatherAPI, WeatherData

logger = logging.getLogger(__name__)


class WeatherCache:
    """Управление кэшем погоды"""

    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.weather_api = WeatherAPI()
        self.cache_prefix = "weather:"
        self.default_ttl = 1800  # 30 минут в секундах

    async def initialize(self):
        """Инициализация Redis"""
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            self.redis_client = await aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            logger.info("✅ Redis подключен")

    async def get_weather(self, city: str, use_cache: bool = True) -> WeatherData:
        """
        Получение погоды с кэшированием.

        Args:
            city: Название города
            use_cache: Использовать ли кэш

        Returns:
            WeatherData объект
        """
        # 1. Пытаемся получить из кэша
        if use_cache:
            cached = await self._get_cached_weather(city)
            if cached:
                logger.debug(f"Данные из кэша для {city}")
                return cached

        # 2. Получаем от API
        async with self.weather_api as api:
            weather_data = await api.get_current_weather(city)

            # 3. Сохраняем в кэш
            if use_cache:
                await self._cache_weather(city, weather_data)

            return weather_data

    async def _get_cached_weather(self, city: str) -> Optional[WeatherData]:
        """Получение данных из кэша"""
        cache_key = f"{self.cache_prefix}{city.lower()}"

        try:
            # Пробуем Redis
            if self.redis_client:
                cached = await self.redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    # Проверяем срок годности
                    updated = datetime.fromisoformat(data['updated_at'])
                    if datetime.now() - updated < timedelta(seconds=self.default_ttl):
                        return WeatherData(**data)

            # Пробуем БД кэш
            async with get_db() as session:
                result = await session.execute("""
                    SELECT * FROM weather_cache 
                    WHERE city = :city AND expires_at > :now
                """, {"city": city, "now": datetime.now()})

                row = result.fetchone()
                if row:
                    return WeatherData(
                        city=row.city,
                        temperature=row.temperature,
                        feels_like=row.feels_like,
                        conditions=row.conditions,
                        humidity=row.humidity,
                        wind_speed=row.wind_speed,
                        pressure=row.pressure,
                        icon=row.icon,
                        sunrise=row.sunrise,
                        sunset=row.sunset,
                        updated_at=row.updated_at
                    )

        except Exception as e:
            logger.error(f"Ошибка получения из кэша {city}: {e}")

        return None

    async def _cache_weather(self, city: str, data: WeatherData):
        """Сохранение в кэш"""
        cache_key = f"{self.cache_prefix}{city.lower()}"

        try:
            # Сохраняем в Redis
            if self.redis_client:
                serialized = json.dumps(data.__dict__, default=str)
                await self.redis_client.setex(
                    cache_key,
                    self.default_ttl,
                    serialized
                )

            # Сохраняем в БД кэш
            async with get_db() as session:
                await session.execute("""
                    INSERT OR REPLACE INTO weather_cache 
                    VALUES (:city, :temp, :feels, :cond, :hum, :wind, 
                            :press, :icon, :sunrise, :sunset, :updated, :expires)
                """, {
                    "city": city,
                    "temp": data.temperature,
                    "feels": data.feels_like,
                    "cond": data.conditions,
                    "hum": data.humidity,
                    "wind": data.wind_speed,
                    "press": data.pressure,
                    "icon": data.icon,
                    "sunrise": data.sunrise,
                    "sunset": data.sunset,
                    "updated": data.updated_at,
                    "expires": data.updated_at + timedelta(seconds=self.default_ttl)
                })
                await session.commit()

        except Exception as e:
            logger.error(f"Ошибка сохранения в кэш {city}: {e}")

    async def update_cities_cache(self, cities: List[str]):
        """
        Массовое обновление кэша для списка городов.

        Args:
            cities: Список городов для обновления
        """
        logger.info(f"Начинаю массовое обновление кэша для {len(cities)} городов")

        success = 0
        failed = 0

        async with self.weather_api as api:
            for city in cities:
                try:
                    weather_data = await api.get_current_weather(city)
                    await self._cache_weather(city, weather_data)
                    success += 1

                    # Не спамим API - пауза между запросами
                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Не удалось обновить кэш для {city}: {e}")
                    failed += 1

        logger.info(f"✅ Обновление завершено. Успешно: {success}, Ошибок: {failed}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Получение статистики кэша"""
        stats = {
            "memory_cache_size": len(self.weather_api.cache),
            "redis_connected": self.redis_client is not None,
            "default_ttl_seconds": self.default_ttl
        }

        if self.redis_client:
            try:
                keys = await self.redis_client.keys(f"{self.cache_prefix}*")
                stats["redis_keys"] = len(keys)
            except:
                stats["redis_keys"] = 0

        # Статистика из БД
        async with get_db() as session:
            result = await session.execute("SELECT COUNT(*) FROM weather_cache")
            stats["db_cache_size"] = result.scalar()

            result = await session.execute("""
                SELECT COUNT(*) FROM weather_cache 
                WHERE expires_at > :now
            """, {"now": datetime.now()})
            stats["db_valid_entries"] = result.scalar()

        return stats

    async def cleanup_expired(self):
        """Очистка устаревших записей в кэше"""
        logger.info("🧹 Очищаю устаревшие записи кэша...")

        # Очищаем in-memory кэш
        expired_keys = []
        for city, (cached_time, _) in self.weather_api.cache.items():
            if datetime.now() - cached_time > timedelta(seconds=self.default_ttl):
                expired_keys.append(city)

        for key in expired_keys:
            del self.weather_api.cache[key]

        # Очищаем Redis
        if self.redis_client:
            try:
                # Используем SCAN для больших баз
                async for key in self.redis_client.scan_iter(f"{self.cache_prefix}*"):
                    ttl = await self.redis_client.ttl(key)
                    if ttl <= 0:
                        await self.redis_client.delete(key)
            except Exception as e:
                logger.error(f"Ошибка очистки Redis: {e}")

        # Очищаем БД кэш
        async with get_db() as session:
            await session.execute("""
                DELETE FROM weather_cache WHERE expires_at <= :now
            """, {"now": datetime.now()})
            deleted = session.rowcount
            await session.commit()

        logger.info(f"✅ Очистка завершена. Удалено: {len(expired_keys)} из памяти, {deleted} из БД")


# Глобальный инстанс
weather_cache = WeatherCache()