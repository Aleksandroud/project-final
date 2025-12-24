import pytest
from wardrobe_app.database.models import User, UserPreferences, Gender
from wardrobe_app.tests.test_bot.test_units import make_message


@pytest.mark.asyncio
async def test_check_command_full_settings(bot, dispatcher, patched_db):
    """Пользователь с полными настройками — /check показывает всё"""

    async with patched_db:
        from wardrobe_app.database.models import User, UserPreferences

        user = User(telegram_id=123456, username="tester", first_name="Тестер")
        await patched_db.add(user)
        await patched_db.flush()

        prefs = UserPreferences(
            user_id=user.id,
            name="Екатерина",
            gender=Gender.FEMALE,
            city="Санкт-Петербург",
            clothing_style=4,  # minimalism
            wants_dispatch=True,
            dispatch_time="08:30",
            timezone="UTC+3"
        )
        await patched_db.add(prefs)
        await patched_db.commit()

    await dispatcher.feed_update(bot, make_message("/check", user_id=123456))

    assert bot.send_message.called
    text = bot.send_message.call_args.kwargs["text"]

    assert "Ваши текущие настройки:" in text
    assert "Имя: Екатерина" in text
    assert "Пол: Женский" in text
    assert "Город: Санкт-Петербург" in text
    assert "Стиль: Минимализм" in text
    assert "Рассылка: Включена" in text
    assert "Часовой пояс: UTC+3" in text
    assert "Время рассылки: 08:30" in text


@pytest.mark.asyncio
async def test_check_command_dispatch_disabled(bot, dispatcher, patched_db):
    """Рассылка выключена — не показываем время и пояс"""

    async with patched_db:
        user = User(telegram_id=987654)
        await patched_db.add(user)
        await patched_db.flush()

        prefs = UserPreferences(
            user_id=user.id,
            name="Алексей",
            gender=Gender.MALE,
            city="Новосибирск",
            clothing_style=2,  # casual
            wants_dispatch=False,
            dispatch_time=None,
            timezone=None
        )
        await patched_db.add(prefs)
        await patched_db.commit()

    await dispatcher.feed_update(bot, make_message("/check", user_id=987654))

    assert bot.send_message.called
    text = bot.send_message.call_args.kwargs["text"]

    assert "Имя: Алексей" in text
    assert "Пол: Мужской" in text
    assert "Город: Новосибирск" in text
    assert "Стиль: Повседневный" in text
    assert "Рассылка: Отключена" in text
    assert "Часовой пояс" not in text
    assert "Время рассылки" not in text


@pytest.mark.asyncio
async def test_check_command_no_user_preferences(bot, dispatcher, patched_db):
    """Пользователь есть в БД, но нет настроек — просим пройти опрос"""

    async with patched_db:
        user = User(telegram_id=555555, username="no_prefs")
        await patched_db.add(user)
        await patched_db.commit()

    await dispatcher.feed_update(bot, make_message("/check", user_id=555555))

    assert bot.send_message.called
    text = bot.send_message.call_args.kwargs["text"]
    assert "Настройки не найдены" in text or "не проходили опрос" in text
    assert "/start" in text


@pytest.mark.asyncio
async def test_check_command_no_user_at_all(bot, dispatcher):
    """Пользователь вообще не существует в БД — просим начать опрос"""

    await dispatcher.feed_update(bot, make_message("/check", user_id=999999))

    assert bot.send_message.called
    text = bot.send_message.call_args.kwargs["text"]
    assert "Вы еще не проходили опрос" in text
    assert "Используйте /start" in text


@pytest.mark.asyncio
async def test_check_command_all_styles_displayed_correctly(bot, dispatcher, patched_db):
    """Проверяем, что все стили отображаются по названию, а не номером"""

    style_numbers = [1, 2, 3, 4, 5]
    expected_names = ["Классический", "Повседневный", "Спортивный", "Минимализм", "Уличный"]

    for style_num, expected_name in zip(style_numbers, expected_names):
        async with patched_db:
            user = User(telegram_id=100000 + style_num)
            await patched_db.add(user)
            await patched_db.flush()

            prefs = UserPreferences(
                user_id=user.id,
                name="СтильТестер",
                gender=Gender.MALE,
                city="Москва",
                clothing_style=style_num,
                wants_dispatch=False
            )
            await patched_db.add(prefs)
            await patched_db.commit()

        await dispatcher.feed_update(bot, make_message("/check", user_id=100000 + style_num))

        assert bot.send_message.called
        text = bot.send_message.call_args.kwargs["text"]
        assert f"Стиль: {expected_name}" in text
        assert str(style_num) not in text