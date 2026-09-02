from __future__ import annotations

from sqlalchemy import select
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


async def grant_bonus_if_first_payment(session: AsyncSession, user: User) -> None:
    """Called right after a payment is marked paid. Grants the referrer a bonus
    only on the referred user's very first successful payment (TZ 4.1)."""
    if user.referrer_id is None:
        return

    prior_paid = await session.execute(
        select(Payment.id).where(Payment.user_id == user.tg_id, Payment.status == "paid")
    )
    if len(prior_paid.all()) != 1:
        return  # not the first payment

    already_granted = await session.scalar(
        select(ReferralBonus).where(ReferralBonus.referred_id == user.tg_id)
    )
    if already_granted:
        return

    bonus_days = settings.REFERRAL_BONUS_DAYS
    bonus_amount = settings.REFERRAL_BONUS_AMOUNT

    session.add(
        ReferralBonus(
            referrer_id=user.referrer_id,
            referred_id=user.tg_id,
            bonus_days=bonus_days,
            bonus_amount=bonus_amount,
        )
    )

    if bonus_amount:
        referrer = await session.get(User, user.referrer_id)
        if referrer:
            referrer.balance += bonus_amount
            session.add(
                BalanceTransaction(
                    user_id=referrer.tg_id,
                    delta=bonus_amount,
                    reason="referral",
                )
            )

    await session.flush()
