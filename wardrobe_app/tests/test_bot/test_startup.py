import pytest
from aiogram import Dispatcher
from wardrobe_app.bot.client import dp


@pytest.mark.asyncio
async def test_dispatcher_starts(async_session, monkeypatch):
    monkeypatch.setattr(
        "wardrobe_app.database.connection.AsyncSessionLocal",
        async_session,
    )

    assert isinstance(dp, Dispatcher)
