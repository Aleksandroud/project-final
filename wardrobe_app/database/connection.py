from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = "sqlite+aiosqlite:///./clothes_bot.db"

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Инициализация БД - создает таблицы только если их нет"""
    from .models import Base

    async with engine.begin() as conn:
        # Создаем таблицы ТОЛЬКО если их нет
        await conn.run_sync(Base.metadata.create_all)

    logger.info("✅ Таблицы готовы (созданы если не существовали)")

async def close_db():
    await engine.dispose()