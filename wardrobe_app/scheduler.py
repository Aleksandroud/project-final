import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

from aiogram import Bot
from wardrobe_app.config import settings
from wardrobe_app.database.connection import get_db
from services.dispatcher import run_morning_dispatch
from services.cache import weather_cache

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler: Optional[AsyncIOScheduler] = None

        self.jobstores = {'default': MemoryJobStore()}
        self.executors = {
            'default': ThreadPoolExecutor(20),
            'processpool': ProcessPoolExecutor(5)
        }
        self.job_defaults = {
            'coalesce': True,
            'max_instances': 3,
            'misfire_grace_time': 300
        }

    async def initialize(self):
        await weather_cache.initialize()

        self.scheduler = AsyncIOScheduler(
            jobstores=self.jobstores,
            executors=self.executors,
            job_defaults=self.job_defaults,
            timezone=timezone.utc
        )

        await self._setup_jobs()
        self._setup_signal_handlers()

    async def _setup_jobs(self):
        self.scheduler.add_job(
            self._run_morning_dispatch,
            IntervalTrigger(minutes=60),
            id='morning_dispatch',
            name='Morning dispatch',
            replace_existing=True
        )

        self.scheduler.add_job(
            self._update_weather_cache,
            CronTrigger(hour=0, minute=0, timezone=timezone.utc),
            id='update_weather_cache',
            name='Update weather cache',
            replace_existing=True
        )

        self.scheduler.add_job(
            self._cleanup_expired_cache,
            IntervalTrigger(hours=6),
            id='cleanup_cache',
            name='Cleanup expired cache',
            replace_existing=True
        )

        self.scheduler.add_job(
            self._log_system_stats,
            IntervalTrigger(hours=1),
            id='system_stats',
            name='System statistics logging',
            replace_existing=True
        )

        self.scheduler.add_job(
            self._health_check,
            IntervalTrigger(minutes=30),
            id='health_check',
            name='System health check',
            replace_existing=True
        )

    async def _run_morning_dispatch(self):
        try:
            result = await run_morning_dispatch(self.bot)
            logger.info(f"Morning dispatch completed: {result}")
        except Exception as e:
            logger.error(f"Dispatch error: {e}")

    async def _update_weather_cache(self):
        try:
            async with get_db() as session:
                result = await session.execute("""
                    SELECT DISTINCT city FROM user_preferences 
                    WHERE city IS NOT NULL AND city != ''
                """)
                cities = [row.city for row in result.fetchall()]

            if not cities:
                return

            await weather_cache.update_cities_cache(cities)
            logger.info(f"Weather cache updated for {len(cities)} cities")

        except Exception as e:
            logger.error(f"Weather cache update error: {e}")

    async def _cleanup_expired_cache(self):
        try:
            await weather_cache.cleanup_expired()
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")

    async def _log_system_stats(self):
        try:
            stats = await weather_cache.get_cache_stats()

            logger.info(
                f"System stats: "
                f"Memory cache: {stats['memory_cache_size']}, "
                f"DB cache: {stats['db_cache_size']}, "
                f"Redis: {'connected' if stats['redis_connected'] else 'disconnected'}"
            )

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
            logger.error(f"Stats logging error: {e}")

    async def _health_check(self):
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "status": "healthy",
            "checks": {}
        }

        try:
            async with get_db() as session:
                await session.execute("SELECT 1")
            health_status["checks"]["database"] = "ok"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "degraded"

        try:
            stats = await weather_cache.get_cache_stats()
            health_status["checks"]["cache"] = "ok"
            health_status["cache_stats"] = stats
        except Exception as e:
            health_status["checks"]["cache"] = f"error: {str(e)}"
            health_status["status"] = "degraded"

        if health_status["status"] != "healthy":
            logger.warning(f"Health check degraded: {health_status}")

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down scheduler...")
        self.shutdown()
        sys.exit(0)

    def start(self):
        if self.scheduler and not self.scheduler.running:
            self.scheduler.start()
            jobs = self.scheduler.get_jobs()
            logger.info(f"Scheduler started with {len(jobs)} jobs")

    def shutdown(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    async def run_immediate(self, task_name: str, **kwargs) -> Dict[str, Any]:
        if task_name == 'morning_dispatch':
            return await self._run_morning_dispatch()
        elif task_name == 'update_cache':
            return await self._update_weather_cache()
        elif task_name == 'cleanup_cache':
            return await self._cleanup_expired_cache()
        else:
            raise ValueError(f"Unknown task: {task_name}")

    def get_scheduler_info(self) -> Dict[str, Any]:
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
                for job in jobs[:10]
            ]
        }


scheduler: Optional[TaskScheduler] = None


async def initialize_scheduler(bot: Bot) -> TaskScheduler:
    global scheduler
    scheduler = TaskScheduler(bot)
    await scheduler.initialize()
    return scheduler


def get_scheduler() -> TaskScheduler:
    if scheduler is None:
        raise RuntimeError("Scheduler not initialized")
    return scheduler