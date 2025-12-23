import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

from aiogram import Bot
from wardrobe_app.config import settings
from wardrobe_app.database.connection import get_db
from services.dispatcher import run_morning_dispatch
from services.cache import weather_cache

from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Продвинутый планировщик задач с сохранением состояния"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.jobstores = {}  # ← БОЛЬШЕ НЕ БУДЕТ СОЗДАВАТЬ ТАБЛИЦУ

        # Вариант 2: MemoryJobStore (рекомендую)
        from apscheduler.jobstores.memory import MemoryJobStore
        self.jobstores = {'default': MemoryJobStore()}  # ← Задачи только в памяти
        self.executors = {
            'default': ThreadPoolExecutor(20),
            'processpool': ProcessPoolExecutor(5)
        }
        self.job_defaults = {
            'coalesce': True,
            'max_instances': 3,
            'misfire_grace_time': 300  # 5 минут
        }

    async def initialize(self):
        """Инициализация планировщика"""
        logger.info("🔄 Инициализация планировщика задач...")

        # Инициализируем кэш
        await weather_cache.initialize()

        # Создаем планировщик
        self.scheduler = AsyncIOScheduler(
            jobstores=self.jobstores,
            executors=self.executors,
            job_defaults=self.job_defaults,
            timezone=timezone.utc
        )

        # Настраиваем задачи
        await self._setup_jobs()

        # Настраиваем обработку сигналов
        self._setup_signal_handlers()

        logger.info("✅ Планировщик инициализирован")

    async def _setup_jobs(self):
        """Настройка всех запланированных задач"""

        # 1. Утренняя рассылка - каждые 60 минут
        self.scheduler.add_job(
            self._run_morning_dispatch,
            IntervalTrigger(minutes=60),
            id='morning_dispatch',
            name='Утренняя рассылка рекомендаций',
            replace_existing=True
        )

        # 2. Обновление кэша погоды - ежедневно в 00:00 UTC
        self.scheduler.add_job(
            self._update_weather_cache,
            CronTrigger(hour=0, minute=0, timezone=timezone.utc),
            id='update_weather_cache',
            name='Обновление кэша погоды',
            replace_existing=True
        )

        # 3. Очистка устаревшего кэша - каждые 6 часов
        self.scheduler.add_job(
            self._cleanup_expired_cache,
            IntervalTrigger(hours=6),
            id='cleanup_cache',
            name='Очистка устаревшего кэша',
            replace_existing=True
        )

        # 4. Статистика и мониторинг - ежечасно
        self.scheduler.add_job(
            self._log_system_stats,
            IntervalTrigger(hours=1),
            id='system_stats',
            name='Логирование системной статистики',
            replace_existing=True
        )

        # 5. Проверка работоспособности API - каждые 30 минут
        self.scheduler.add_job(
            self._health_check,
            IntervalTrigger(minutes=30),
            id='health_check',
            name='Проверка работоспособности системы',
            replace_existing=True
        )

        logger.info(f"Настроено {len(self.scheduler.get_jobs())} задач")

    async def _run_morning_dispatch(self):
        """Задача: утренняя рассылка"""
        logger.info("⏰ Запуск утренней рассылки...")
        try:
            result = await run_morning_dispatch(self.bot)
            logger.info(f"✅ Рассылка завершена: {result}")
        except Exception as e:
            logger.error(f"❌ Ошибка рассылки: {e}")

    async def _update_weather_cache(self):
        """Задача: обновление кэша погоды"""
        logger.info("🔄 Начинаю обновление кэша погоды...")

        try:
            # Получаем все уникальные города из БД
            async with get_db() as session:
                result = await session.execute("""
                    SELECT DISTINCT city FROM user_preferences 
                    WHERE city IS NOT NULL AND city != ''
                """)
                cities = [row.city for row in result.fetchall()]

            if not cities:
                logger.info("Нет городов для обновления кэша")
                return

            logger.info(f"Обновляю кэш для {len(cities)} городов...")

            # Обновляем кэш
            await weather_cache.update_cities_cache(cities)

            logger.info(f"✅ Кэш обновлен для {len(cities)} городов")

        except Exception as e:
            logger.error(f"❌ Ошибка обновления кэша: {e}")

    async def _cleanup_expired_cache(self):
        """Задача: очистка устаревшего кэша"""
        logger.info("🧹 Очистка устаревшего кэша...")
        try:
            await weather_cache.cleanup_expired()
            logger.info("✅ Очистка кэша завершена")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки кэша: {e}")

    async def _log_system_stats(self):
        """Задача: логирование статистики"""
        try:
            stats = await weather_cache.get_cache_stats()

            logger.info(
                f"📊 Системная статистика: "
                f"Кэш в памяти: {stats['memory_cache_size']}, "
                f"БД кэш: {stats['db_cache_size']}, "
                f"Redis: {'✓' if stats['redis_connected'] else '✗'}"
            )

            # Сохраняем статистику в БД для истории
            async with get_db() as session:
                await session.execute("""
                    INSERT INTO system_stats 
                    (timestamp, cache_size, db_cache_size, redis_connected)
                    VALUES (:ts, :cache, :db_cache, :redis)
                """, {
                    "ts": datetime.now(),
                    "cache": stats['memory_cache_size'],
                    "db_cache": stats['db_cache_size'],
                    "redis": stats['redis_connected']
                })
                await session.commit()

        except Exception as e:
            logger.error(f"❌ Ошибка сбора статистики: {e}")

    async def _health_check(self):
        """Задача: проверка работоспособности"""
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "status": "healthy",
            "checks": {}
        }

        try:
            # Проверка базы данных
            async with get_db() as session:
                await session.execute("SELECT 1")
            health_status["checks"]["database"] = "ok"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "degraded"

        try:
            # Проверка кэша
            stats = await weather_cache.get_cache_stats()
            health_status["checks"]["cache"] = "ok"
            health_status["cache_stats"] = stats
        except Exception as e:
            health_status["checks"]["cache"] = f"error: {str(e)}"
            health_status["status"] = "degraded"

        # Логируем статус здоровья
        if health_status["status"] == "healthy":
            logger.debug("✅ Проверка здоровья: все системы работают")
        else:
            logger.warning(f"⚠️ Проверка здоровья: {health_status}")

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов для graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Обработчик сигналов завершения"""
        logger.info(f"Получен сигнал {signum}, останавливаю планировщик...")
        self.shutdown()
        sys.exit(0)

    def start(self):
        """Запуск планировщика"""
        if self.scheduler and not self.scheduler.running:
            self.scheduler.start()
            logger.info("🚀 Планировщик задач запущен")

            # Выводим список задач
            jobs = self.scheduler.get_jobs()
            logger.info(f"Активные задачи ({len(jobs)}):")
            for job in jobs:
                logger.info(f"  • {job.name} ({job.id}) - следующий запуск: {job.next_run_time}")

    def shutdown(self):
        """Остановка планировщика"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("🛑 Планировщик остановлен")

    async def run_immediate(self, task_name: str, **kwargs) -> Dict[str, Any]:
        """
        Немедленный запуск задачи.

        Args:
            task_name: Имя задачи (morning_dispatch, update_cache и т.д.)

        Returns:
            Результат выполнения
        """
        if task_name == 'morning_dispatch':
            return await self._run_morning_dispatch()
        elif task_name == 'update_cache':
            return await self._update_weather_cache()
        elif task_name == 'cleanup_cache':
            return await self._cleanup_expired_cache()
        else:
            raise ValueError(f"Неизвестная задача: {task_name}")

    def get_scheduler_info(self) -> Dict[str, Any]:
        """Возвращает информацию о планировщике"""
        if not self.scheduler:
            return {"status": "not_initialized"}

        jobs = self.scheduler.get_jobs()

        return {
            "status": "running" if self.scheduler.running else "stopped",
            "job_count": len(jobs),
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                }
                for job in jobs[:10]  # Первые 10 задач
            ]
        }


# Глобальный инстанс
scheduler: Optional[TaskScheduler] = None


async def initialize_scheduler(bot: Bot) -> TaskScheduler:
    """Инициализация глобального планировщика"""
    global scheduler
    scheduler = TaskScheduler(bot)
    await scheduler.initialize()
    return scheduler


def get_scheduler() -> TaskScheduler:
    """Получение глобального планировщика"""
    if scheduler is None:
        raise RuntimeError("Планировщик не инициализирован")
    return scheduler