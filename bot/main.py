from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings
from bot.database.db import init_db
from bot.handlers import menu, profile, purchase, start
from bot.handlers.admin import build_admin_router
from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.errors import ErrorLoggingMiddleware
from bot.scheduler.jobs import register_jobs
from bot.services.marzban import marzban_client
from bot.utils.logging import setup_logging

logger = logging.getLogger("bot.main")


async def main() -> None:
    setup_logging()
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(ErrorLoggingMiddleware())
    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(profile.router)
    dp.include_router(purchase.router)
    dp.include_router(build_admin_router())

    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, bot)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await marzban_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
