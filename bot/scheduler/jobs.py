from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from bot.database.db import async_session_maker
from bot.database.models import Subscription
from bot.services.subscriptions import deactivate

logger = logging.getLogger("bot.scheduler")

REMINDER_TEXT = {
    3: "Ваша VPN-подписка истекает через 3 дня. Рекомендуем продлить её заранее, чтобы не остаться без связи!",
    1: "Внимание! Ваша подписка истекает завтра. Нажмите «Продлить», чтобы сохранить доступ к сети.",
}


async def send_reminders(bot: Bot) -> None:
    async with async_session_maker() as session:
        now = dt.datetime.utcnow()
        subs = (
            await session.execute(select(Subscription).where(Subscription.status == "active"))
        ).scalars().all()

        for sub in subs:
            if not sub.expires_at:
                continue
            days_left = (sub.expires_at.date() - now.date()).days

            if days_left == 3 and not sub.reminder_3d_sent:
                await _notify(bot, sub.user_id, REMINDER_TEXT[3])
                sub.reminder_3d_sent = True
            elif days_left == 1 and not sub.reminder_1d_sent:
                await _notify(bot, sub.user_id, REMINDER_TEXT[1])
                sub.reminder_1d_sent = True

        await session.commit()


async def expire_sweep(bot: Bot) -> None:
    async with async_session_maker() as session:
        now = dt.datetime.utcnow()
        subs = (
            await session.execute(
                select(Subscription).where(Subscription.status == "active", Subscription.expires_at < now)
            )
        ).scalars().all()

        for sub in subs:
            await deactivate(session, sub)
            await _notify(bot, sub.user_id, "Ваша подписка истекла. Доступ к VPN ограничен.")

        await session.commit()


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.exception("Failed to notify user %s", user_id)


def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(send_reminders, "interval", hours=1, args=[bot], id="send_reminders")
    scheduler.add_job(expire_sweep, "interval", hours=1, args=[bot], id="expire_sweep")
