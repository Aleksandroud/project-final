import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from wardrobe_app.config import settings
from wardrobe_app.bot.client import dp
from wardrobe_app.database.connection import init_db, close_db
from wardrobe_app.scheduler import initialize_scheduler
from wardrobe_app.services.cache import weather_cache

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
    await init_db()
    await weather_cache.initialize()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    scheduler = await initialize_scheduler(bot)
    scheduler.start()

    yield {"bot": bot, "scheduler": scheduler}

    scheduler.shutdown()
    await close_db()
    await bot.session.close()


async def main():
    async with lifespan() as context:
        bot = context["bot"]
        try:
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Critical error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())