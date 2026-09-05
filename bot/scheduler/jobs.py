from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from bot.database.db import async_session_maker
from bot.database.models import Connection
from bot.services.free_period import is_free_period_active
from bot.services.subscriptions import deactivate

logger = logging.getLogger("bot.scheduler")

REMINDER_TEXT = {
    3: 'Подключение «{name}» истекает через 3 дня. Продлите его заранее, чтобы не остаться без связи!',
    1: 'Внимание! Подключение «{name}» истекает завтра. Нажмите «Продлить», чтобы сохранить доступ.',
}


async def send_reminders(bot: Bot) -> None:
    async with async_session_maker() as session:
        if await is_free_period_active(session):
            return
        now = dt.datetime.utcnow()
        conns = (
            await session.execute(select(Connection).where(Connection.status == "active"))
        ).scalars().all()

        for conn in conns:
            if not conn.expires_at:
                continue
            days_left = (conn.expires_at.date() - now.date()).days

            if days_left == 3 and not conn.reminder_3d_sent:
                await _notify(bot, conn.user_id, REMINDER_TEXT[3].format(name=conn.name))
                conn.reminder_3d_sent = True
            elif days_left == 1 and not conn.reminder_1d_sent:
                await _notify(bot, conn.user_id, REMINDER_TEXT[1].format(name=conn.name))
                conn.reminder_1d_sent = True

        await session.commit()


async def expire_sweep(bot: Bot) -> None:
    async with async_session_maker() as session:
        if await is_free_period_active(session):
            return
        now = dt.datetime.utcnow()
        conns = (
            await session.execute(
                select(Connection).where(Connection.status == "active", Connection.expires_at < now)
            )
        ).scalars().all()

        for conn in conns:
            await deactivate(session, conn)
            await _notify(bot, conn.user_id, f'Подключение «{conn.name}» истекло. Доступ ограничен.')

        await session.commit()


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.exception("Failed to notify user %s", user_id)


def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(send_reminders, "interval", hours=1, args=[bot], id="send_reminders")
    scheduler.add_job(expire_sweep, "interval", hours=1, args=[bot], id="expire_sweep")
