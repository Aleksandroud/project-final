import pytest
from wardrobe_app.database.models import User, UserPreferences, Gender
from wardrobe_app.bot.keyboards import STYLE_TO_NUMBER
from wardrobe_app.tests.test_bot.test_units import make_message, make_callback, get_all


@pytest.mark.asyncio
async def test_full_survey_flow_success(bot, dispatcher, patched_db, monkeypatch):
    """Полный успешный опрос с включённой рассылкой и всеми шагами"""

    async def mock_validate_city(city_name: str):
        if "москва" in city_name.lower():
            return True, {"timezone": 10800}
        return False, None

    from wardrobe_app.bot import client
    monkeypatch.setattr(client, "validate_city_with_weather_api", mock_validate_city)

    await dispatcher.feed_update(bot, make_message("/start"))

    assert bot.send_message.called
    assert "Как вас зовут?" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_message("Анастасия"))

    assert "Приятно познакомиться, Анастасия!" in bot.send_message.call_args.kwargs["text"]
    assert "Укажите ваш пол" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_callback("gender_female"))

    assert bot.edit_message_text.called
    assert "Пол выбран: Женский" in bot.edit_message_text.call_args.kwargs["text"]
    assert "В каком городе вы живете?" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_message("Москва"))

    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Город 'Москва' найден!" in last_text
    assert "Часовой пояс автоматически определен: UTC+3" in last_text
    assert "Хотите ли вы получать ежедневные рекомендации" in last_text

    await dispatcher.feed_update(bot, make_callback("enable_dispatch_yes"))

    assert "Во сколько вам удобно получать рекомендации утром?" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_message("09:00"))

    assert "Выберите ваш стиль одежды" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_callback("style_casual"))

    final_text = bot.send_message.call_args.kwargs["text"]
    assert "Настройка завершена и сохранена!" in final_text
    assert "Анастасия" in final_text
    assert "Женский" in final_text
    assert "Москва" in final_text
    assert "Повседневный" in final_text

    async with patched_db:
        users = await get_all(User)
        prefs_list = await get_all(UserPreferences)

        assert len(users) == 1
        assert len(prefs_list) == 1

        prefs = prefs_list[0]
        assert prefs.name == "Анастасия"
        assert prefs.gender == Gender.FEMALE
        assert prefs.city == "Москва"
        assert prefs.timezone == "UTC+3"
        assert prefs.clothing_style == STYLE_TO_NUMBER["casual"]
        assert prefs.wants_dispatch is True
        assert prefs.dispatch_time == "09:00"


@pytest.mark.asyncio
async def test_survey_invalid_name(bot, dispatcher, patched_db):
    """Короткое имя — бот просит повторить"""
    await dispatcher.feed_update(bot, make_message("/start"))
    await dispatcher.feed_update(bot, make_message("А"))

    assert bot.send_message.called
    assert "минимум 2 символа" in bot.send_message.call_args.kwargs["text"].lower()


@pytest.mark.asyncio
async def test_survey_invalid_city(bot, dispatcher, patched_db, monkeypatch):
    """Невалидный город — повторный запрос"""
    async def mock_validate_city(city_name: str):
        return False, "Город не найден"

    from wardrobe_app.bot import client
    monkeypatch.setattr(client, "validate_city_with_weather_api", mock_validate_city)

    await dispatcher.feed_update(bot, make_message("/start"))
    await dispatcher.feed_update(bot, make_message("Алексей"))
    await dispatcher.feed_update(bot, make_callback("gender_male"))
    await dispatcher.feed_update(bot, make_message("НесуществующийГород"))

    assert "не найден" in bot.send_message.call_args.kwargs["text"]
    assert "Введите город еще раз" in bot.send_message.call_args.kwargs["text"]

    async with patched_db:
        prefs = (await get_all(UserPreferences))
        if prefs:
            assert prefs[0].city != "НесуществующийГород"


@pytest.mark.asyncio
async def test_survey_dispatch_off_no_time(bot, dispatcher, patched_db, monkeypatch):
    """Отключение рассылки — пропускаем шаг с временем"""
    monkeypatch.setattr(
        "wardrobe_app.bot.client.validate_city_with_weather_api",
        lambda x: (True, {"timezone": 10800})
    )

    await dispatcher.feed_update(bot, make_message("/start"))
    await dispatcher.feed_update(bot, make_message("Иван"))
    await dispatcher.feed_update(bot, make_callback("gender_male"))
    await dispatcher.feed_update(bot, make_message("Москва"))
    await dispatcher.feed_update(bot, make_callback("enable_dispatch_no"))  # Отключаем

    assert "Выберите ваш стиль одежды" in bot.send_message.call_args.kwargs["text"]

    await dispatcher.feed_update(bot, make_callback("style_minimalism"))

    async with patched_db:
        prefs = (await get_all(UserPreferences))[0]
        assert prefs.wants_dispatch is False
        assert prefs.dispatch_time is None


@pytest.mark.asyncio
async def test_survey_all_styles(bot, dispatcher, patched_db, monkeypatch):
    """Проверяем, что все стили сохраняются корректно"""
    monkeypatch.setattr(
        "wardrobe_app.bot.client.validate_city_with_weather_api",
        lambda x: (True, {"timezone": 0})
    )

    style_callbacks = ["classic", "casual", "sporty", "minimalism", "streetwear"]
    expected_numbers = [1, 2, 3, 4, 5]

    for callback, expected in zip(style_callbacks, expected_numbers):
        await dispatcher.feed_update(bot, make_message("/start"))
        await dispatcher.feed_update(bot, make_message("Тест"))
        await dispatcher.feed_update(bot, make_callback("gender_male"))
        await dispatcher.feed_update(bot, make_message("London"))
        await dispatcher.feed_update(bot, make_callback("enable_dispatch_no"))
        await dispatcher.feed_update(bot, make_callback(f"style_{callback}"))

        async with patched_db:
            prefs = (await get_all(UserPreferences))[-1]
            assert prefs.clothing_style == expected


@pytest.mark.asyncio
async def test_survey_repeat_start_clears_state(bot, dispatcher, patched_db):
    """Повторный /start очищает состояние и начинает заново"""
    await dispatcher.feed_update(bot, make_message("/start"))
    await dispatcher.feed_update(bot, make_message("СтароеИмя"))

    await dispatcher.feed_update(bot, make_message("/start"))

    assert "Как вас зовут?" in bot.send_message.call_args.kwargs["text"]