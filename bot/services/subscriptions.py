from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Subscription
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
    label = f"user_{user_id}"
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


async def get_or_create_subscription(session: AsyncSession, user_id: int) -> Subscription:
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None:
        sub = Subscription(user_id=user_id, status="inactive")
        session.add(sub)
        await session.flush()
    return sub


async def activate_or_extend(
    session: AsyncSession, user_id: int, period_days: int, protocol: str | None = None
) -> Subscription:
    """Create (first purchase) or extend (renewal) the user's VPN access.

    Four protocols are available (see TZ 3.2-3.4): AmneziaWG (default,
    obfuscated), plain WireGuard (faster, no obfuscation), and VLESS-Reality
    / Shadowsocks via Marzban. `protocol` picks which one a freshly-created
    peer uses; existing peers keep their protocol unless the caller passes a
    new one. A peer has no built-in expiry, so our own `expires_at` is the
    source of truth — the scheduler's expire_sweep() removes it when it
    lapses. If the subscription is still within its current period (renewal
    before expiry) and the protocol isn't changing, the peer already exists
    and we simply push `expires_at` out. A lapsed subscription's peer was
    already deleted by expire_sweep(), so reactivating it means requesting a
    brand-new one — the bot just resends the fresh config.
    """
    sub = await get_or_create_subscription(session, user_id)
    now = dt.datetime.utcnow()
    target_protocol = protocol or sub.protocol

    needs_new_peer = (
        sub.awg_public_key is None or sub.status != "active" or target_protocol != sub.protocol
    )

    if needs_new_peer:
        if sub.awg_public_key and sub.status == "active":
            await _deprovision(sub.awg_public_key, sub.protocol)
        new_expire = now + dt.timedelta(days=period_days)
        identity, config = await _provision(user_id, target_protocol, new_expire)
        sub.awg_public_key = identity
        sub.awg_config = config
        sub.protocol = target_protocol
    else:
        base = sub.expires_at if (sub.expires_at and sub.expires_at > now) else now
        new_expire = base + dt.timedelta(days=period_days)
        if sub.protocol in MARZBAN_FAMILY:
            await marzban_client.modify_expire(sub.awg_public_key, new_expire)

    sub.expires_at = new_expire
    sub.status = "active"
    sub.reminder_3d_sent = False
    sub.reminder_1d_sent = False
    await session.flush()
    return sub


async def switch_protocol(session: AsyncSession, user_id: int, new_protocol: str) -> Subscription:
    """Move an active subscription's peer to a different protocol, keeping
    `expires_at` untouched — unlike activate_or_extend, this isn't a
    purchase, just a client-side preference (see TZ 3.3-3.4)."""
    sub = await get_or_create_subscription(session, user_id)
    if sub.status != "active":
        raise ValueError("subscription is not active")
    if sub.protocol == new_protocol:
        return sub

    if sub.awg_public_key:
        await _deprovision(sub.awg_public_key, sub.protocol)

    identity, config = await _provision(user_id, new_protocol, sub.expires_at)
    sub.awg_public_key = identity
    sub.awg_config = config
    sub.protocol = new_protocol
    await session.flush()
    return sub


async def deactivate(session: AsyncSession, sub: Subscription) -> None:
    if sub.awg_public_key:
        await _deprovision(sub.awg_public_key, sub.protocol)
    sub.status = "expired"
    await session.flush()
