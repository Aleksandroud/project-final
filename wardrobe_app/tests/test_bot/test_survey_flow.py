import pytest
from wardrobe_app.tests.test_bot.test_units import make_message, make_callback

@pytest.mark.asyncio
async def test_full_survey_flow(bot, dispatcher, patched_db):
    """
    Полный flow:
    /start → имя → пол → город → рассылка → время → стиль
    """

    await dispatcher.feed_update(
        bot,
        make_message("/start"),
    )

    await dispatcher.feed_update(
        bot,
        make_message("Анастасия"),
    )

    await dispatcher.feed_update(
        bot,
        make_callback("gender_female"),
    )

    await dispatcher.feed_update(
        bot,
        make_message("Москва"),
    )

    await dispatcher.feed_update(
        bot,
        make_callback("dispatch_on"),
    )

    await dispatcher.feed_update(
        bot,
        make_callback("time_09_00"),
    )

    await dispatcher.feed_update(
        bot,
        make_callback("style_casual"),
    )

    async with patched_db:
        from wardrobe_app.database.models import User, UserPreferences

        users = await get_all(User)
        prefs = await get_all(UserPreferences)

        assert len(users) == 1
        assert prefs[0].city == "Москва"
        assert prefs[0].clothing_style == "casual"
