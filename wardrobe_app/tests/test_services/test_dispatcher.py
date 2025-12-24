import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError

from wardrobe_app.services.dispatcher import MorningDispatcher
from wardrobe_app.services.weather import WeatherData
from wardrobe_app.database.models import User, UserPreferences, Gender


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
async def dispatcher(mock_bot, session_maker):
    disp = MorningDispatcher(mock_bot)

    disp.stats = {
        "total_sent": 0,
        "total_failed": 0,
        "last_success": None,
        "cities_processed": 0
    }

    yield disp


@pytest.fixture
def mock_weather_data():
    return WeatherData(
        city="Moscow",
        temperature=15.0,
        feels_like=14.0,
        conditions="Облачно",
        humidity=70,
        wind_speed=10.0,
        pressure=1015,
        icon="cloud.png",
        updated_at=datetime.now()
    )


@pytest.mark.asyncio
@patch("wardrobe_app.services.dispatcher.get_clothing_recommendation", return_value="Надень куртку и джинсы.")
@patch("wardrobe_app.services.dispatcher.weather_cache.get_weather")
async def test_run_dispatch_sends_personalized_messages(
    mock_get_weather,
    mock_recommendation,
    dispatcher,
    mock_bot,
    session_maker,
    mock_weather_data
):
    mock_get_weather.return_value = mock_weather_data

    async with session_maker() as session:
        async with session.begin():
            user1 = User(telegram_id=111111, username="user1")
            user2 = User(telegram_id=222222, username="user2")
            session.add_all([user1, user2])
            await session.flush()

            prefs1 = UserPreferences(
                user_id=user1.id,
                name="Алексей",
                gender=Gender.MALE,
                city="Moscow",
                clothing_style=2,  # casual
                wants_dispatch=True,
                dispatch_time="08:00",
                timezone="UTC+3"
            )
            prefs2 = UserPreferences(
                user_id=user2.id,
                name="Мария",
                gender=Gender.FEMALE,
                city="Moscow",
                clothing_style=4,  # minimalism
                wants_dispatch=True,
                dispatch_time="08:00",
                timezone="UTC+3"
            )
            session.add_all([prefs1, prefs2])

    fake_now = datetime(2025, 12, 24, 6, 0, 0, tzinfo=timezone.utc)  # 09:00 по Мск

    with patch("wardrobe_app.services.dispatcher.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        result = await dispatcher.run_dispatch()

    assert result["status"] == "success"
    assert result["sent"] == 2
    assert result["failed"] == 0

    assert mock_bot.send_message.call_count == 2

    first_call = mock_bot.send_message.call_args_list[0].kwargs
    assert "Доброе утро, Алексей!" in first_call["text"]
    assert "Облачно" in first_call["text"]
    assert "Надень куртку и джинсы." in first_call["text"]
    assert first_call["chat_id"] == 111111

    second_call = mock_bot.send_message.call_args_list[1].kwargs
    assert "Доброе утро, Мария!" in second_call["text"]
    assert second_call["chat_id"] == 222222

    assert mock_recommendation.call_count == 2
    assert mock_recommendation.call_args_list[0][1]["gender"] == "male"
    assert mock_recommendation.call_args_list[0][1]["style"] == 2
    assert mock_recommendation.call_args_list[1][1]["gender"] == "female"
    assert mock_recommendation.call_args_list[1][1]["style"] == 4


@pytest.mark.asyncio
@patch("wardrobe_app.services.dispatcher.get_clothing_recommendation", return_value="Лёгкая одежда")
@patch("wardrobe_app.services.dispatcher.weather_cache.get_weather")
async def test_dispatch_handles_blocked_user(
    mock_get_weather,
    dispatcher,
    mock_bot,
    session_maker,
    mock_weather_data
):
    mock_get_weather.return_value = mock_weather_data

    async with session_maker() as session:
        async with session.begin():
            user = User(telegram_id=999999)
            session.add(user)
            await session.flush()
            prefs = UserPreferences(
                user_id=user.id,
                name="Блокер",
                city="SPb",
                wants_dispatch=True,
                dispatch_time="07:00",
                timezone="UTC+3"
            )
            session.add(prefs)

    fake_now = datetime(2025, 12, 24, 5, 0, tzinfo=timezone.utc)

    mock_bot.send_message.side_effect = [None, TelegramForbiddenError(MagicMock())]

    with patch("wardrobe_app.services.dispatcher.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now

        result = await dispatcher.run_dispatch()

    assert result["status"] == "success"
    assert result["sent"] == 1
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_get_users_for_dispatch_respects_timezone_and_time_window(
    dispatcher,
    session_maker
):
    async with session_maker() as session:
        async with session.begin():
            u1 = User(telegram_id=1001)
            u2 = User(telegram_id=1002)
            u3 = User(telegram_id=1003)
            session.add_all([u1, u2, u3])
            await session.flush()

            session.add_all([
                UserPreferences(user_id=u1.id, wants_dispatch=True, dispatch_time="09:00", timezone="UTC+3"),  # Москва
                UserPreferences(user_id=u2.id, wants_dispatch=True, dispatch_time="09:00", timezone="UTC+0"),  # Лондон
                UserPreferences(user_id=u3.id, wants_dispatch=True, dispatch_time="09:00", timezone="UTC+9"),  # Токио
            ])

    fake_now = datetime(2025, 12, 24, 6, 0, tzinfo=timezone.utc)

    with patch("wardrobe_app.services.dispatcher.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        users = await dispatcher._get_users_for_dispatch()

    assert len(users) == 1
    assert users[0].telegram_id == 1001  # только москвич


@pytest.mark.asyncio
async def test_dispatch_no_users(
    dispatcher
):
    result = await dispatcher.run_dispatch()
    assert result["status"] == "no_users"
    assert result["count"] == 0