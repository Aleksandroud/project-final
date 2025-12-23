from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from . import models


class UserCRUD:
    @staticmethod
    async def get_user(db: AsyncSession, telegram_id: int):
        result = await db.execute(
            select(models.User).where(models.User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(db: AsyncSession, telegram_id: int, **kwargs):
        user = models.User(
            telegram_id=telegram_id,
            username=kwargs.get("username"),
            first_name=kwargs.get("first_name")
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


class PreferencesCRUD:
    @staticmethod
    async def create_or_update_preferences(db: AsyncSession, user_id: int, **preferences):
        result = await db.execute(
            select(models.UserPreferences).where(models.UserPreferences.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in preferences.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
        else:
            existing = models.UserPreferences(
                user_id=user_id,
                **preferences
            )
            db.add(existing)

        await db.commit()
        await db.refresh(existing)
        return existing