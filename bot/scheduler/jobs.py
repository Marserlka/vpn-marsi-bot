from __future__ import annotations

import datetime as dt
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import or_, select

from bot.config import settings
from bot.database.db import async_session_maker
from bot.database.models import Connection
from bot.services.free_period import is_free_period_active
from bot.services.subscriptions import charge_connection_day

logger = logging.getLogger("bot.scheduler")


async def daily_billing(bot: Bot) -> None:
    """Runs frequently (see register_jobs) but each connection is only
    actually charged once its own next_charge_at has passed, then that
    cursor is pushed a day forward — so a short poll interval doesn't cause
    double-billing. Connections that never got a next_charge_at (shouldn't
    happen post-migration, but defensively handled) are treated as due now.
    """
    async with async_session_maker() as session:
        if await is_free_period_active(session):
            return
        now = dt.datetime.utcnow()
        conns = (
            await session.execute(
                select(Connection).where(
                    Connection.status == "active",
                    or_(Connection.next_charge_at.is_(None), Connection.next_charge_at <= now),
                )
            )
        ).scalars().all()

        for conn in conns:
            if conn.next_charge_at is None:
                conn.next_charge_at = now
            charged = await charge_connection_day(session, conn)
            if not charged:
                await _notify(
                    bot,
                    conn.user_id,
                    f'Подключение «{conn.name}» отключено — не хватило средств на балансе для '
                    f'списания {settings.PRICE_PER_DAY_RUB} руб./день. Пополните баланс и создайте новое подключение.',
                )

        await session.commit()


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.exception("Failed to notify user %s", user_id)


def register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(daily_billing, "interval", minutes=30, args=[bot], id="daily_billing")
