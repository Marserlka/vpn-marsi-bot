from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Subscription
from bot.services.awg_agent import awg_agent

logger = logging.getLogger("bot.subscriptions")


async def get_or_create_subscription(session: AsyncSession, user_id: int) -> Subscription:
    sub = await session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None:
        sub = Subscription(user_id=user_id, status="inactive")
        session.add(sub)
        await session.flush()
    return sub


async def activate_or_extend(session: AsyncSession, user_id: int, period_days: int) -> Subscription:
    """Create (first purchase) or extend (renewal) the user's VPN access.

    AmneziaWG is the primary protocol (see TZ 3.2): VLESS-Reality proved
    less stable in real-world testing, while AmneziaWG held up. A peer has
    no built-in expiry, so our own `expires_at` is the
    source of truth — the scheduler's expire_sweep() removes the peer via
    the awg_agent when it lapses. If the subscription is still within its
    current period (renewal before expiry), the peer already exists and we
    simply push `expires_at` out — no agent call needed. A lapsed
    subscription's peer was already deleted by expire_sweep(), so
    reactivating it means requesting a brand-new peer (new keys/IP), which
    is fine — the bot just resends the fresh config to the user.
    """
    sub = await get_or_create_subscription(session, user_id)
    now = dt.datetime.utcnow()

    needs_new_peer = sub.awg_public_key is None or sub.status != "active"

    if needs_new_peer:
        peer = await awg_agent.create_peer(label=f"user_{user_id}")
        sub.awg_public_key = peer["public_key"]
        sub.awg_config = peer["client_config"]
        new_expire = now + dt.timedelta(days=period_days)
    else:
        base = sub.expires_at if (sub.expires_at and sub.expires_at > now) else now
        new_expire = base + dt.timedelta(days=period_days)

    sub.expires_at = new_expire
    sub.status = "active"
    sub.reminder_3d_sent = False
    sub.reminder_1d_sent = False
    await session.flush()
    return sub


async def deactivate(session: AsyncSession, sub: Subscription) -> None:
    if sub.awg_public_key:
        try:
            await awg_agent.delete_peer(sub.awg_public_key)
        except Exception:
            logger.exception("Failed to delete AmneziaWG peer for subscription %s", sub.id)
    sub.status = "expired"
    await session.flush()
