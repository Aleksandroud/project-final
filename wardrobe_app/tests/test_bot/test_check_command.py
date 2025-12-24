import pytest
from wardrobe_app.tests.test_bot.test_units import make_message

@pytest.mark.asyncio
async def test_check_command(bot, dispatcher, patched_db, sent_messages):
    await dispatcher.feed_update(bot, make_message("/check"))

    assert len(sent_messages) > 0
    text = sent_messages[-1]["text"]

    assert "Москва" in text
