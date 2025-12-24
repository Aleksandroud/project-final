import pytest
from wardrobe_app.tests.test_bot.test_units import make_message, make_callback, get_user_preferences

@pytest.mark.asyncio
async def test_change_city(bot, dispatcher, patched_db, user_with_preferences):
    await dispatcher.feed_update(
        bot,
        make_message("/settings"),
    )

    await dispatcher.feed_update(
        bot,
        make_callback("change_city"),
    )

    await dispatcher.feed_update(
        bot,
        make_message("Санкт-Петербург"),
    )

    prefs = await get_user_preferences()

    assert prefs.city == "Санкт-Петербург"
