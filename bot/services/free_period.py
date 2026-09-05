from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Connection
from bot.services.settings import get_settings


async def is_free_period_active(session: AsyncSession) -> bool:
    row = await get_settings(session)
    return bool(row.free_period_enabled)


async def enable_free_period(session: AsyncSession) -> None:
    row = await get_settings(session)
    if row.free_period_enabled:
        return
    row.free_period_enabled = True
    row.free_period_started_at = dt.datetime.utcnow()
    await session.flush()


async def disable_free_period(session: AsyncSession) -> dt.timedelta:
    """Shifts every active connection's next_charge_at forward by exactly
    how long the free period lasted, so nobody actually gets billed for
    time spent inside it (see TZ) — the scheduler's daily_billing() skips
    everyone while free_period_enabled is set, so next_charge_at is
    untouched until this runs. Returns the shifted duration (zero if it
    wasn't running, e.g. a double-click)."""
    row = await get_settings(session)
    if not row.free_period_enabled or row.free_period_started_at is None:
        row.free_period_enabled = False
        row.free_period_started_at = None
        await session.flush()
        return dt.timedelta()

    duration = dt.datetime.utcnow() - row.free_period_started_at

    conns = (
        await session.execute(
            select(Connection).where(Connection.status == "active", Connection.next_charge_at.is_not(None))
        )
    ).scalars().all()
    for conn in conns:
        conn.next_charge_at = conn.next_charge_at + duration

    row.free_period_enabled = False
    row.free_period_started_at = None
    await session.flush()
    return duration
