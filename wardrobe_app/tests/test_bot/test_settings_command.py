import pytest
from wardrobe_app.bot.keyboards import STYLE_TO_NUMBER
from wardrobe_app.tests.test_bot.test_units import (
    make_message,
    make_callback,
    get_user_preferences,
)


@pytest.mark.asyncio
async def test_settings_opens_menu(bot, dispatcher, user_with_preferences):
    """Проверяет, что /settings открывает меню с тремя кнопками"""
    await dispatcher.feed_update(bot, make_message("/settings"))

    assert bot.send_message.called
    text = bot.send_message.call_args.kwargs["text"]
    assert "Что вы хотите изменить?" in text

    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    button_texts = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert "Город" in button_texts
    assert "Стиль одежды" in button_texts
    assert "Настройки рассылки" in button_texts


@pytest.mark.asyncio
async def test_change_city_success(
    bot, dispatcher, user_with_preferences, monkeypatch
):
    """Успешное изменение города с автоопределением часового пояса"""
    async def mock_validate_city(city_name: str):
        if "петербург" in city_name.lower():
            return True, {"timezone": 10800}
        return False, None

    from wardrobe_app.bot import client
    monkeypatch.setattr(client, "validate_city_with_weather_api", mock_validate_city)

    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_city"))
    await dispatcher.feed_update(bot, make_message("Санкт-Петербург"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Город обновлён на Санкт-Петербург" in last_text or "найден" in last_text
    assert "UTC+3" in last_text

    prefs = await get_user_preferences()
    assert prefs.city == "Санкт-Петербург"
    assert prefs.timezone == "UTC+3"


@pytest.mark.asyncio
async def test_change_city_invalid_city(
    bot, dispatcher, user_with_preferences, monkeypatch
):
    """Невалидный город — бот просит ввести заново"""
    async def mock_validate_city(city_name: str):
        return False, "Город не найден"

    from wardrobe_app.bot import client
    monkeypatch.setattr(client, "validate_city_with_weather_api", mock_validate_city)

    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_city"))
    await dispatcher.feed_update(bot, make_message("НесуществующийГород123"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Город 'НесуществующийГород123' не найден" in last_text
    assert "Введите город еще раз" in last_text

    prefs = await get_user_preferences()
    assert prefs.city != "НесуществующийГород123"


@pytest.mark.asyncio
async def test_change_style_success(bot, dispatcher, user_with_preferences):
    """Успешное изменение стиля одежды"""
    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_style"))
    await dispatcher.feed_update(bot, make_callback("style_streetwear"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Стиль одежды обновлён" in last_text
    assert "Уличный" in last_text

    prefs = await get_user_preferences()
    assert prefs.clothing_style == STYLE_TO_NUMBER["streetwear"]


@pytest.mark.asyncio
async def test_change_dispatch_enable_with_time(
    bot, dispatcher, user_with_preferences
):
    """Включение рассылки с указанием времени"""
    prefs = await get_user_preferences()
    prefs.wants_dispatch = False
    prefs.dispatch_time = None

    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_dispatch"))
    await dispatcher.feed_update(bot, make_callback("enable_dispatch_yes"))
    await dispatcher.feed_update(bot, make_message("07:30"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Ежедневная рассылка включена" in last_text or "во сколько" in last_text.lower()

    prefs = await get_user_preferences()
    assert prefs.wants_dispatch is True
    assert prefs.dispatch_time == "07:30"


@pytest.mark.asyncio
async def test_change_dispatch_disable(bot, dispatcher, user_with_preferences):
    """Отключение рассылки"""
    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_dispatch"))
    await dispatcher.feed_update(bot, make_callback("enable_dispatch_no"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "Ежедневная рассылка отключена" in last_text

    prefs = await get_user_preferences()
    assert prefs.wants_dispatch is False
    assert prefs.dispatch_time is None


@pytest.mark.asyncio
async def test_change_dispatch_invalid_time(
    bot, dispatcher, user_with_preferences
):
    """Некорректное время — бот просит ввести заново"""
    await dispatcher.feed_update(bot, make_message("/settings"))
    await dispatcher.feed_update(bot, make_callback("change_dispatch"))
    await dispatcher.feed_update(bot, make_callback("enable_dispatch_yes"))
    await dispatcher.feed_update(bot, make_message("25:00"))

    assert bot.send_message.called
    last_text = bot.send_message.call_args.kwargs["text"]
    assert "неверный формат" in last_text.lower() or "повторите" in last_text.lower()

    prefs = await get_user_preferences()
    assert prefs.wants_dispatch is False or prefs.dispatch_time != "25:00"