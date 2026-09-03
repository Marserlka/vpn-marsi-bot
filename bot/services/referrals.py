from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, Payment, ReferralBonus, User


async def register_referral(session: AsyncSession, user: User, referrer_id: int) -> None:
    if user.referrer_id is not None or referrer_id == user.tg_id:
        return
    referrer = await session.get(User, referrer_id)
    if referrer is None:
        return
    user.referrer_id = referrer_id
    await session.flush()


async def grant_bonus_for_payment(session: AsyncSession, user: User, payment: Payment) -> None:
    """Called after every payment is marked paid (not just the first one):
    the referrer earns REFERRAL_BONUS_PERCENT% of that payment's amount plus
    a flat REFERRAL_BONUS_DAYS-day top-up, each time their referral pays."""
    if user.referrer_id is None:
        return

    bonus_amount = payment.amount * settings.REFERRAL_BONUS_PERCENT // 100
    bonus_days = settings.REFERRAL_BONUS_DAYS

    session.add(
        ReferralBonus(
            referrer_id=user.referrer_id,
            referred_id=user.tg_id,
            bonus_days=bonus_days,
            bonus_amount=bonus_amount,
        )
    )

    referrer = await session.get(User, user.referrer_id)
    if referrer is None:
        await session.flush()
        return

    if bonus_amount:
        referrer.balance += bonus_amount
        session.add(
            BalanceTransaction(
                user_id=referrer.tg_id,
                delta=bonus_amount,
                reason="referral",
            )
        )

    if bonus_days:
        from bot.services.subscriptions import extend_connection, list_connections

        # A referrer can have several connections now (see TZ 3.5) — the
        # bonus days go to whichever one is currently active; if they have
        # none, there's nothing sensible to extend, so it's skipped (the
        # cash bonus above still applies either way).
        referrer_conns = await list_connections(session, referrer.tg_id)
        target = next((c for c in referrer_conns if c.status == "active"), None)
        if target:
            await extend_connection(session, target, bonus_days)

    await session.flush()
