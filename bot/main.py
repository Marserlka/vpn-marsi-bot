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
from bot.handlers import balance, menu, profile, purchase, start, test
from bot.handlers.admin import build_admin_router
from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.errors import ErrorLoggingMiddleware
from bot.middlewares.force_subscribe import ForceSubscribeMiddleware
from bot.scheduler.jobs import register_jobs
from bot.services.awg_agent import awg_agent
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
    # Registered on message/callback_query specifically, NOT dp.update — at
    # the update level `event` is the raw Update object, which has no
    # `.from_user` at all, so `getattr(event, "from_user", None)` always
    # returned None and the whole check silently no-opped for every user
    # (found 2026-09-05: force-sub showed "enabled" in the admin panel, bot
    # was a channel admin, chat_id was correct, and it still never prompted
    # anyone). Message/CallbackQuery genuinely have `.from_user`, matching
    # the isinstance() checks already in the middleware's own body.
    force_sub = ForceSubscribeMiddleware()
    dp.message.middleware(force_sub)
    dp.callback_query.middleware(force_sub)

    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(profile.router)
    dp.include_router(balance.router)
    dp.include_router(purchase.router)
    dp.include_router(build_admin_router())
    dp.include_router(test.router)

    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, bot)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await marzban_client.close()
        await awg_agent.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
