from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Connection
from bot.services.awg_agent import awg_agent
from bot.services.marzban import marzban_client

logger = logging.getLogger("bot.subscriptions")

WG_FAMILY = {"amnezia", "wireguard"}
MARZBAN_FAMILY = {"vless", "ss"}


async def _provision(user_id: int, protocol: str, expire_at: dt.datetime) -> tuple[str, str]:
    """Create a peer/user for `protocol` and return (identity, client_config).

    `identity` is what `_deprovision` needs later to remove it again — an
    AmneziaWG/WireGuard public key for the WG family, a Marzban username for
    the VLESS/Shadowsocks family.
    """
    label = f"user_{user_id}_{int(dt.datetime.utcnow().timestamp())}"
    if protocol in WG_FAMILY:
        peer = await awg_agent.create_peer(label=label, protocol=protocol)
        return peer["public_key"], peer["client_config"]
    if protocol in MARZBAN_FAMILY:
        user = await marzban_client.create_user(label, expire_at, protocol=protocol)
        return label, user["links"][0]
    raise ValueError(f"unknown protocol: {protocol}")


async def _deprovision(identity: str, protocol: str) -> None:
    try:
        if protocol in WG_FAMILY:
            await awg_agent.delete_peer(identity, protocol=protocol)
        elif protocol in MARZBAN_FAMILY:
            await marzban_client.remove_user(identity)
    except Exception:
        logger.exception("Failed to remove %s peer/user %s", protocol, identity)


async def list_connections(session: AsyncSession, user_id: int) -> list[Connection]:
    result = await session.execute(
        select(Connection).where(Connection.user_id == user_id).order_by(Connection.id)
    )
    return list(result.scalars().all())


async def get_connection(session: AsyncSession, connection_id: int, user_id: int) -> Connection | None:
    return await session.scalar(
        select(Connection).where(Connection.id == connection_id, Connection.user_id == user_id)
    )


async def create_connection(
    session: AsyncSession, user_id: int, name: str, protocol: str, region: str, period_days: int
) -> Connection:
    """Provision a brand-new, paid connection. Always makes a new peer/user
    — unlike the old single-subscription model, there's no "existing one to
    extend" here, this is called once per purchase of a new connection."""
    now = dt.datetime.utcnow()
    expire_at = now + dt.timedelta(days=period_days)
    identity, config = await _provision(user_id, protocol, expire_at)

    conn = Connection(
        user_id=user_id,
        name=name,
        protocol=protocol,
        region=region,
        awg_public_key=identity,
        awg_config=config,
        status="active",
        expires_at=expire_at,
    )
    session.add(conn)
    await session.flush()
    return conn


async def extend_connection(session: AsyncSession, conn: Connection, period_days: int) -> Connection:
    """Renew an existing connection. If it lapsed, its peer/user was already
    removed by expire_sweep(), so this re-provisions a fresh one; otherwise
    it just pushes `expires_at` out."""
    now = dt.datetime.utcnow()
    if conn.status != "active" or conn.awg_public_key is None:
        new_expire = now + dt.timedelta(days=period_days)
        identity, config = await _provision(conn.user_id, conn.protocol, new_expire)
        conn.awg_public_key = identity
        conn.awg_config = config
    else:
        base = conn.expires_at if (conn.expires_at and conn.expires_at > now) else now
        new_expire = base + dt.timedelta(days=period_days)
        if conn.protocol in MARZBAN_FAMILY:
            await marzban_client.modify_expire(conn.awg_public_key, new_expire)

    conn.expires_at = new_expire
    conn.status = "active"
    conn.reminder_3d_sent = False
    conn.reminder_1d_sent = False
    await session.flush()
    return conn


async def regenerate_connection(session: AsyncSession, conn: Connection) -> Connection:
    """Kill the current peer/user and issue a fresh one for the same
    connection — same name/protocol/region/expiry, new keys."""
    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)
    expire_at = conn.expires_at or (dt.datetime.utcnow() + dt.timedelta(days=30))
    identity, config = await _provision(conn.user_id, conn.protocol, expire_at)
    conn.awg_public_key = identity
    conn.awg_config = config
    await session.flush()
    return conn


async def switch_protocol(session: AsyncSession, conn: Connection, new_protocol: str) -> Connection:
    """Move a connection to a different protocol, keeping `expires_at`
    untouched — a client-side preference, not a purchase."""
    if conn.status != "active":
        raise ValueError("connection is not active")
    if conn.protocol == new_protocol:
        return conn

    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)

    expire_at = conn.expires_at or (dt.datetime.utcnow() + dt.timedelta(days=30))
    identity, config = await _provision(conn.user_id, new_protocol, expire_at)
    conn.awg_public_key = identity
    conn.awg_config = config
    conn.protocol = new_protocol
    await session.flush()
    return conn


async def deactivate(session: AsyncSession, conn: Connection) -> None:
    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)
    conn.status = "expired"
    await session.flush()
