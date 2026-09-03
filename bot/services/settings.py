from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import BotSettings

SETTINGS_ROW_ID = 1


async def get_settings(session: AsyncSession) -> BotSettings:
    row = await session.get(BotSettings, SETTINGS_ROW_ID)
    if row is None:
        row = BotSettings(id=SETTINGS_ROW_ID)
        session.add(row)
        await session.flush()
    return row
