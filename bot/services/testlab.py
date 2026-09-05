from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import CdnFrontingLabConfig, OlcRtcLabConfig

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


async def get_cdn_config(session: AsyncSession) -> CdnFrontingLabConfig:
    row = await session.get(CdnFrontingLabConfig, CONFIG_ROW_ID)
    if row is None:
        row = CdnFrontingLabConfig(id=CONFIG_ROW_ID)
        session.add(row)
        await session.flush()
    return row


async def set_cdn_config(
    session: AsyncSession,
    *,
    domain: str | None = None,
    cf_zone_id: str | None = None,
    cf_api_token: str | None = None,
    vless_uuid: str | None = None,
    ws_path: str | None = None,
    notes: str | None = None,
) -> CdnFrontingLabConfig:
    row = await get_cdn_config(session)
    if domain is not None:
        row.domain = domain
    if cf_zone_id is not None:
        row.cf_zone_id = cf_zone_id
    if cf_api_token is not None:
        row.cf_api_token = cf_api_token
    if vless_uuid is not None:
        row.vless_uuid = vless_uuid
    if ws_path is not None:
        row.ws_path = ws_path
    if notes is not None:
        row.notes = notes
    row.updated_at = dt.datetime.utcnow()
    await session.flush()
    return row
