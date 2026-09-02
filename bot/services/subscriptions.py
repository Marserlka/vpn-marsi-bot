from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Subscription
from bot.services.marzban import marzban_client

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

    Mirrors TZ 3.1/4.2: brand-new Marzban user gets `ips_limit=1`; an existing,
    still-active subscription is simply pushed further out; an expired one is
    re-enabled in Marzban and its countdown restarts from now.
    """
    sub = await get_or_create_subscription(session, user_id)
    now = dt.datetime.utcnow()

    if sub.marzban_username is None:
        sub.marzban_username = f"vpnmarsi_{user_id}_{uuid.uuid4().hex[:6]}"
        new_expire = now + dt.timedelta(days=period_days)
        marzban_user = await marzban_client.create_user(sub.marzban_username, new_expire)
        sub.subscription_url = marzban_client.subscription_url_from(marzban_user, settings.MARZBAN_BASE_URL)
    else:
        base = sub.expires_at if (sub.expires_at and sub.expires_at > now and sub.status == "active") else now
        new_expire = base + dt.timedelta(days=period_days)
        await marzban_client.modify_expire(sub.marzban_username, new_expire, status="active")

    sub.expires_at = new_expire
    sub.status = "active"
    sub.reminder_3d_sent = False
    sub.reminder_1d_sent = False
    await session.flush()
    return sub


async def deactivate(session: AsyncSession, sub: Subscription) -> None:
    if sub.marzban_username:
        try:
            await marzban_client.disable_user(sub.marzban_username)
        except Exception:
            logger.exception("Failed to disable Marzban user %s", sub.marzban_username)
    sub.status = "expired"
    await session.flush()
