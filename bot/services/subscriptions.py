from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, Connection, User
from bot.services.awg_agent import awg_agent
from bot.services.marzban import marzban_client

logger = logging.getLogger("bot.subscriptions")

WG_FAMILY = {"amnezia", "wireguard"}
MARZBAN_FAMILY = {"vless", "ss"}


async def _provision(user_id: int, protocol: str) -> tuple[str, str]:
    """Create a peer/user for `protocol` and return (identity, client_config).

    `identity` is what `_deprovision` needs later to remove it again — an
    AmneziaWG/WireGuard public key for the WG family, a Marzban username for
    the VLESS/Shadowsocks family. No expiry is passed anywhere here — since
    2026-09-05 lifecycle is entirely balance-driven (see charge_connection_day),
    not a fixed date either side has to agree on.

    For the Marzban family, `client_config` is the subscription URL, not a
    bare vless://ss:// link (2026-09-05, see TZ) — same "add by link" UX for
    the user, but it's what lets a later custom JSON template
    (USE_CUSTOM_JSON_FOR_*) inject our own routing rules, since a raw link
    has no template behind it at all.
    """
    label = f"user_{user_id}_{int(dt.datetime.utcnow().timestamp())}"
    if protocol in WG_FAMILY:
        peer = await awg_agent.create_peer(label=label, protocol=protocol)
        return peer["public_key"], peer["client_config"]
    if protocol in MARZBAN_FAMILY:
        user = await marzban_client.create_user(label, None, protocol=protocol)
        sub_url = marzban_client.subscription_url_from(user, settings.MARZBAN_BASE_URL)
        return label, sub_url
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
    session: AsyncSession, user_id: int, name: str, protocol: str, region: str
) -> Connection:
    """Provision a brand-new connection. Always makes a new peer/user —
    there's no "existing one to extend" here, this is called once per new
    connection. Doesn't touch the owner's balance — the caller is
    responsible for that (see charge_connection_day). Billing starts
    immediately (next_charge_at=now) — the old 3-day free trial was
    replaced by a flat one-time balance bonus at registration (2026-09-05,
    see bot/handlers/start.py and TZ)."""
    now = dt.datetime.utcnow()
    identity, config = await _provision(user_id, protocol)

    conn = Connection(
        user_id=user_id,
        name=name,
        protocol=protocol,
        region=region,
        awg_public_key=identity,
        awg_config=config,
        status="active",
        expires_at=None,
        next_charge_at=now,
    )
    session.add(conn)
    await session.flush()
    return conn


async def charge_connection_day(session: AsyncSession, conn: Connection) -> bool:
    """Debits PRICE_PER_DAY_RUB from the connection owner's balance and
    pushes next_charge_at a day forward. If the balance can't cover it, the
    connection is deactivated immediately instead (no grace period — see TZ
    2026-09-05) and this returns False so the caller can notify the owner.
    """
    user = await session.get(User, conn.user_id)
    if user is None or user.balance < settings.PRICE_PER_DAY_RUB:
        await deactivate(session, conn)
        return False

    user.balance -= settings.PRICE_PER_DAY_RUB
    session.add(BalanceTransaction(user_id=user.tg_id, delta=-settings.PRICE_PER_DAY_RUB, reason="daily_charge"))

    now = dt.datetime.utcnow()
    base = conn.next_charge_at if (conn.next_charge_at and conn.next_charge_at > now) else now
    conn.next_charge_at = base + dt.timedelta(days=1)
    await session.flush()
    return True


async def grant_free_days(session: AsyncSession, conn: Connection, days: int) -> Connection:
    """Admin-only manual credit (see bot/handlers/admin/users.py) — pushes
    next_charge_at forward by `days` without touching the user's balance.
    If the connection had already been deactivated, re-provisions a fresh
    peer/user for it first, same as regenerate_connection/switch_protocol do."""
    now = dt.datetime.utcnow()
    if conn.status != "active" or conn.awg_public_key is None:
        identity, config = await _provision(conn.user_id, conn.protocol)
        conn.awg_public_key = identity
        conn.awg_config = config
        conn.status = "active"
        base = now
    else:
        base = conn.next_charge_at if (conn.next_charge_at and conn.next_charge_at > now) else now

    conn.next_charge_at = base + dt.timedelta(days=days)
    await session.flush()
    return conn


async def regenerate_connection(session: AsyncSession, conn: Connection) -> Connection:
    """Kill the current peer/user and issue a fresh one for the same
    connection — same name/protocol/region/billing cursor, new keys."""
    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)
    identity, config = await _provision(conn.user_id, conn.protocol)
    conn.awg_public_key = identity
    conn.awg_config = config
    await session.flush()
    return conn


async def switch_protocol(session: AsyncSession, conn: Connection, new_protocol: str) -> Connection:
    """Move a connection to a different protocol, keeping its billing cursor
    untouched — a client-side preference, not a purchase."""
    if conn.status != "active":
        raise ValueError("connection is not active")
    if conn.protocol == new_protocol:
        return conn

    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)

    identity, config = await _provision(conn.user_id, new_protocol)
    conn.awg_public_key = identity
    conn.awg_config = config
    conn.protocol = new_protocol
    if new_protocol in MARZBAN_FAMILY:
        # no per-region peer for this family — the subscription bundles
        # every inbound (see _provision's docstring), so "region" no longer
        # means anything specific once switched here.
        conn.region = "all"
    await session.flush()
    return conn


async def deactivate(session: AsyncSession, conn: Connection) -> None:
    if conn.awg_public_key:
        await _deprovision(conn.awg_public_key, conn.protocol)
    conn.status = "expired"
    await session.flush()
