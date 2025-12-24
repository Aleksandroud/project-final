import pytest
from datetime import datetime, timedelta
from fakeredis.aioredis import FakeRedis
from wardrobe_app.services.cache import WeatherCache, WeatherData
from wardrobe_app.config import settings

@pytest.fixture
async def weather_cache(session_maker):
    cache = WeatherCache()
    await cache.initialize()
    cache.redis_client = FakeRedis(decode_responses=True)
    yield cache
    await cache.redis_client.flushall()

@pytest.mark.asyncio
async def test_get_weather_redis_cache_hit(weather_cache, respx_mock):
    city = "Berlin"
    data = WeatherData(
        city=city,
        temperature=20.0,
        feels_like=19.0,
        conditions="Ясно",
        humidity=50,
        wind_speed=10.0,
        pressure=1015,
        icon="sun.png",
        updated_at=datetime.now()
    )

    respx_mock.get("http://api.weatherapi.com/v1/current.json").mock(return_value=Response(200, json={}))

    # Вручную кладём в Redis
    serialized = data.__dict__
    serialized["updated_at"] = serialized["updated_at"].isoformat()
    await weather_cache.redis_client.setex(f"weather:{city.lower()}", 1800, str(serialized))

    result = await weather_cache.get_weather(city)

    assert result.temperature == 20.0
    assert result.conditions == "Ясно"


@pytest.mark.asyncio
async def test_get_weather_db_fallback_when_no_redis(weather_cache, session_maker, respx_mock):
    city = "Tokyo"
    old_data = WeatherData(
        city=city,
        temperature=28.0,
        feels_like=30.0,
        conditions="Жарко",
        humidity=80,
        wind_speed=5.0,
        pressure=1005,
        icon="hot.png",
        updated_at=datetime.now() - timedelta(minutes=10)
    )

    weather_cache.redis_client = None

    expires = old_data.updated_at + timedelta(seconds=1800)
    async with session_maker() as session:
        await session.execute("""
            INSERT OR REPLACE INTO weather_cache VALUES 
            (:city, :temp, :feels, :cond, :hum, :wind, :press, :icon, NULL, NULL, :updated, :expires)
        """, {
            "city": city,
            "temp": old_data.temperature,
            "feels": old_data.feels_like,
            "cond": old_data.conditions,
            "hum": old_data.humidity,
            "wind": old_data.wind_speed,
            "press": old_data.pressure,
            "icon": old_data.icon,
            "updated": old_data.updated_at,
            "expires": expires
        })
        await session.commit()

    result = await weather_cache.get_weather(city)

    assert result.temperature == 28.0
    assert result.conditions == "Жарко"


@pytest.mark.asyncio
async def test_cache_expiration(weather_cache, respx_mock):
    city = "Sydney"

    respx_mock.get("http://api.weatherapi.com/v1/current.json").mock(
        return_value=Response(200, json={
            "current": {
                "temp_c": 30.0,
                "feelslike_c": 32.0,
                "condition": {"text": "Очень жарко"},
                "humidity": 60,
                "wind_kph": 8.0,
                "pressure_mb": 1010,
            }
        })
    )

    await weather_cache.get_weather(city)

    with pytest.monkeypatch.context() as m:
        m.setattr("datetime.datetime", type("obj", (object,), {
            "now": lambda: datetime.now() + timedelta(seconds=2000)
        })())
        result = await weather_cache.get_weather(city)

    assert result.temperature == 30.0