from aiogram.types import CallbackQuery
from wardrobe_app.database.models import UserPreferences
from aiogram.types import Update, Message, Chat, User
from datetime import datetime
import itertools
from sqlalchemy import select
from wardrobe_app.database.connection import AsyncSessionLocal

_message_id = itertools.count(1)
_update_id = itertools.count(1)

async def get_user_preferences(session):
    result = await session.execute(
        select(UserPreferences)
    )
    return result.scalar_one()


def make_message(
    text: str,
    user_id: int = 1,
    chat_id: int = 1,
    username: str = "test_user",
    first_name: str = "Test",
) -> Update:
    message = Message(
        message_id=next(_message_id),
        date=datetime.now(),
        chat=Chat(
            id=chat_id,
            type="private",
        ),
        from_user=User(
            id=user_id,
            is_bot=False,
            first_name=first_name,
            username=username,
        ),
        text=text,
    )

    return Update(
        update_id=next(_update_id),
        message=message,
    )


def make_callback(
    data: str,
    user_id: int = 1,
    chat_id: int = 1,
    message_text: str = "callback",
) -> Update:
    """
    Создаёт Update с CallbackQuery
    """
    message = Message(
        message_id=next(_message_id),
        date=datetime.now(),
        chat=Chat(
            id=chat_id,
            type="private",
        ),
        from_user=User(
            id=user_id,
            is_bot=False,
            first_name="Test",
        ),
        text=message_text,
    )

    callback = CallbackQuery(
        id=str(next(_message_id)),
        from_user=message.from_user,
        chat_instance="test",
        data=data,
        message=message,
    )

    return Update(callback_query=callback)


async def get_all(model):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(model))
        return result.scalars().all()

