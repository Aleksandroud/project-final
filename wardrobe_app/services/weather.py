import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from wardrobe_app.config import settings
from wardrobe_app.database.connection import get_db

logger = logging.getLogger(__name__)


@dataclass
class WeatherData:
    city: str
    temperature: float
    feels_like: float
    conditions: str
    humidity: int
    wind_speed: float
    pressure: int
    icon: str
    sunrise: Optional[int] = None
    sunset: Optional[int] = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.now()

class WeatherAPI:
    def __init__(self):
        self.base_url = "http://api.weatherapi.com/v1"
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Tuple[datetime, WeatherData]] = {}
        self.cache_ttl = timedelta(minutes=30)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        await self._init_cache_table()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _init_cache_table(self):
        async with get_db() as session:
            await session.execute("""
                CREATE TABLE IF NOT EXISTS weather_cache (
                    city TEXT PRIMARY KEY,
                    temperature REAL,
                    feels_like REAL,
                    conditions TEXT,
                    humidity INTEGER,
                    wind_speed REAL,
                    pressure INTEGER,
                    icon TEXT,
                    sunrise INTEGER,
                    sunset INTEGER,
                    updated_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            await session.commit()

    async def get_current_weather(self, city: str, force_refresh: bool = False) -> WeatherData:
        if not force_refresh:
            cached = await self._get_from_cache(city)
            if cached:
                return cached

        db_cached = await self._get_from_db_cache(city)
        if db_cached and not force_refresh:
            await self._save_to_memory_cache(city, db_cached)
            return db_cached

        try:
            weather_data = await self._fetch_from_api(city)
            await self._save_to_cache(city, weather_data)
            return weather_data
        except Exception as e:
            logger.error(f"Weather API error for {city}: {e}")
            fallback = db_cached or cached
            if fallback:
                return fallback
            raise

    async def _fetch_from_api(self, city: str) -> WeatherData:
        if not settings.WEATHERAPI_KEY:
            raise ValueError("API key not configured")

        url = f"{self.base_url}/current.json"
        params = {
            "key": settings.WEATHERAPI_KEY,
            "q": city,
            "lang": "ru",
            "aqi": "no"
        }

        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"API error {response.status}: {error_text}")
                raise Exception(f"API returned error {response.status}")

            data = await response.json()

            return WeatherData(
                city=city,
                temperature=data["current"]["temp_c"],
                feels_like=data["current"]["feelslike_c"],
                conditions=data["current"]["condition"]["text"],
                humidity=data["current"]["humidity"],
                wind_speed=data["current"]["wind_kph"],
                pressure=data["current"]["pressure_mb"],
                icon=data["current"]["condition"]["icon"],
                sunrise=None,
                sunset=None,
                updated_at=datetime.now()
            )

    async def _get_from_cache(self, city: str) -> Optional[WeatherData]:
        if city in self.cache:
            cached_time, data = self.cache[city]
            if datetime.now() - cached_time < self.cache_ttl:
                return data
        return None

    async def _get_from_db_cache(self, city: str) -> Optional[WeatherData]:
        async with get_db() as session:
            result = await session.execute(
                "SELECT * FROM weather_cache WHERE city = :city AND expires_at > :now",
                {"city": city, "now": datetime.now()}
            )
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
        return None

    async def _save_to_cache(self, city: str, data: WeatherData):
        self.cache[city] = (datetime.now(), data)

        async with get_db() as session:
            await session.execute("""
                INSERT OR REPLACE INTO weather_cache 
                (city, temperature, feels_like, conditions, humidity, 
                 wind_speed, pressure, icon, sunrise, sunset, updated_at, expires_at)
                VALUES (:city, :temp, :feels, :cond, :hum, :wind, :press, 
                        :icon, :sunrise, :sunset, :updated, :expires)
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
                "expires": data.updated_at + self.cache_ttl
            })
            await session.commit()

    async def validate_city(self, city: str) -> Tuple[bool, Optional[str]]:
        url = f"{self.base_url}/search.json"
        params = {
            "key": settings.WEATHERAPI_KEY,
            "q": city
        }

        try:
            async with self.session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return len(data) > 0, None
                elif response.status == 400:
                    return False, "Город не найден"
                else:
                    return False, f"API error: {response.status}"
        except Exception as e:
            logger.error(f"City validation error for {city}: {e}")
            return True, None


weather_api = WeatherAPI()