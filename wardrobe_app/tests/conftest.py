import asyncio
import pytest
import pytest_asyncio
from aiogram.types import Message
from datetime import datetime
from aiogram import Bot, Dispatcher

from wardrobe_app.bot.client import dp
from wardrobe_app.config import settings

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wardrobe_app.database.models import Base


@pytest_asyncio.fixture
async def sent_messages(monkeypatch):
    messages = []

    async def fake_send_message(self, chat_id, text, **kwargs):
        messages.append({
            "chat_id": chat_id,
            "text": text,
            "kwargs": kwargs,
        })

        return Message(
            message_id=999,
            date=datetime.now(),
            chat=None,
        )

    monkeypatch.setattr(
        "aiogram.client.bot.Bot.send_message",
        fake_send_message,
    )

    return messages


@pytest_asyncio.fixture
async def patched_db(async_session, monkeypatch):
    monkeypatch.setattr(
        "wardrobe_app.database.connection.AsyncSessionLocal",
        async_session,
    )
    yield

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_maker(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def async_session(session_maker):
    return session_maker


@pytest_asyncio.fixture
async def bot():
    """
    Тестовый экземпляр бота
    """
    return Bot(token=settings.BOT_TOKEN)


@pytest_asyncio.fixture
async def dispatcher():
    """
    Dispatcher, который используется в приложении
    """
    return dp
