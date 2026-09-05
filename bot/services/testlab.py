from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import OlcRtcLabConfig

CONFIG_ROW_ID = 1


async def get_olcrtc_config(session: AsyncSession) -> OlcRtcLabConfig:
    row = await session.get(OlcRtcLabConfig, CONFIG_ROW_ID)
    if row is None:
        row = OlcRtcLabConfig(id=CONFIG_ROW_ID)
        session.add(row)
        await session.flush()
    return row


async def set_olcrtc_config(
    session: AsyncSession,
    *,
    conference_id: str | None = None,
    encryption_key: str | None = None,
    socks5_port: int | None = None,
    notes: str | None = None,
) -> OlcRtcLabConfig:
    row = await get_olcrtc_config(session)
    if conference_id is not None:
        row.conference_id = conference_id
    if encryption_key is not None:
        row.encryption_key = encryption_key
    if socks5_port is not None:
        row.socks5_port = socks5_port
    if notes is not None:
        row.notes = notes
    row.updated_at = dt.datetime.utcnow()
    await session.flush()
    return row
