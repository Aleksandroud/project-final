import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import respx
from httpx import Response

from wardrobe_app.services.weather import WeatherAPI, WeatherData
from wardrobe_app.config import settings

@pytest.fixture
async def weather_api():
    async with WeatherAPI() as api:
        yield api

@pytest.fixture(autouse=True)
def mock_weather_api_key(monkeypatch):
    monkeypatch.setattr(settings, "WEATHERAPI_KEY", "fake_key")

@pytest.mark.asyncio
async def test_fetch_from_api_success(weather_api, respx_mock):
    city = "Moscow"

    respx_mock.get("http://api.weatherapi.com/v1/current.json").mock(
        return_value=Response(
            200,
            json={
                "current": {
                    "temp_c": 22.5,
                    "feelslike_c": 21.0,
                    "condition": {"text": "Солнечно", "icon": "//cdn.weatherapi.com/weather/64x64/day/113.png"},
                    "humidity": 65,
                    "wind_kph": 12.0,
                    "pressure_mb": 1013,
                }
            }
        )
    )

    data = await weather_api._fetch_from_api(city)

    assert isinstance(data, WeatherData)
    assert data.city == city
    assert data.temperature == 22.5
    assert data.feels_like == 21.0
    assert data.conditions == "Солнечно"
    assert data.humidity == 65
    assert data.wind_speed == 12.0
    assert data.pressure == 1013
    assert "113.png" in data.icon
    assert data.updated_at is not None


@pytest.mark.asyncio
async def test_get_current_weather_uses_memory_cache(weather_api):
    city = "London"
    fake_data = WeatherData(
        city=city,
        temperature=18.0,
        feels_like=17.5,
        conditions="Облачно",
        humidity=70,
        wind_speed=15.0,
        pressure=1010,
        icon="icon.png",
        updated_at=datetime.now()
    )

    weather_api.cache[city] = (datetime.now(), fake_data)

    result = await weather_api.get_current_weather(city)

    assert result == fake_data


@pytest.mark.asyncio
async def test_get_current_weather_fallback_on_api_error(weather_api, respx_mock, session_maker):
    city = "Paris"

    old_data = WeatherData(
        city=city,
        temperature=10.0,
        feels_like=8.0,
        conditions="Дождь",
        humidity=90,
        wind_speed=20.0,
        pressure=1000,
        icon="rain.png",
        updated_at=datetime.now() - timedelta(minutes=20)
    )
    expires_at = old_data.updated_at + timedelta(minutes=30)

    async with session_maker() as session:
        await session.execute("""
            INSERT OR REPLACE INTO weather_cache 
            (city, temperature, feels_like, conditions, humidity, wind_speed, pressure, icon, updated_at, expires_at)
            VALUES (:city, :temp, :feels, :cond, :hum, :wind, :press, :icon, :updated, :expires)
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
            "expires": expires_at
        })
        await session.commit()

    respx_mock.get("http://api.weatherapi.com/v1/current.json").mock(
        return_value=Response(500)
    )

    result = await weather_api.get_current_weather(city)

    assert result.temperature == 10.0
    assert result.conditions == "Дождь"


@pytest.mark.asyncio
async def test_validate_city_success(weather_api, respx_mock):
    respx_mock.get("http://api.weatherapi.com/v1/search.json").mock(
        return_value=Response(200, json=[{"name": "Moscow", "country": "Russia"}])
    )

    valid, error = await weather_api.validate_city("Moscow")
    assert valid is True
    assert error is None


@pytest.mark.asyncio
async def test_validate_city_not_found(weather_api, respx_mock):
    respx_mock.get("http://api.weatherapi.com/v1/search.json").mock(
        return_value=Response(200, json=[])
    )

    valid, error = await weather_api.validate_city("InvalidCity123")
    assert valid is False
    assert error == "Город не найден"