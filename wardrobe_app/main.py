import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from wardrobe_app.config import settings
from wardrobe_app.bot.client import dp
from wardrobe_app.database.connection import init_db, close_db
from wardrobe_app.scheduler import initialize_scheduler, get_scheduler
from services.cache import weather_cache

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wardrobe_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan():
    """Управление жизненным циклом приложения"""
    # Startup
    logger.info("🚀 Запуск гардеробного бота...")

    # Инициализация базы данных
    await init_db()
    logger.info("✅ База данных готова")

    # Инициализация кэша
    await weather_cache.initialize()
    logger.info("✅ Кэш инициализирован")

    # Инициализация бота
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Инициализация планировщика
    scheduler = await initialize_scheduler(bot)
    scheduler.start()

    yield {"bot": bot, "scheduler": scheduler}

    # Shutdown
    logger.info("👋 Остановка приложения...")

    scheduler.shutdown()
    await close_db()
    await bot.session.close()

    logger.info("✅ Приложение остановлено корректно")


async def main():
    """Основная функция запуска"""
    async with lifespan() as context:
        bot = context["bot"]

        try:
            logger.info("🤖 Бот запущен. Ожидаю сообщений...")
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")