from __future__ import annotations

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, ReferralBonus, User


async def register_referral(session: AsyncSession, user: User, referrer_id: int) -> None:
    if user.referrer_id is not None or referrer_id == user.tg_id:
        return
    referrer = await session.get(User, referrer_id)
    if referrer is None:
        return
    user.referrer_id = referrer_id
    await session.flush()


async def grant_referral_bonus_if_first_topup(session: AsyncSession, bot: Bot, user: User) -> None:
    """Called every time a balance top-up is confirmed (see
    bot/handlers/purchase.py:apply_paid_payment). The referrer earns a flat,
    one-time REFERRAL_BONUS_RUB cash bonus, credited only the first time
    their referral ever tops up — a ReferralBonus row already existing for
    this referred_id is the dedup check that stops it firing again on
    later top-ups (see TZ 2026-09-05)."""
    if user.referrer_id is None or not settings.REFERRAL_BONUS_RUB:
        return

    already = await session.scalar(
        select(ReferralBonus).where(ReferralBonus.referred_id == user.tg_id)
    )
    if already is not None:
        return

    referrer = await session.get(User, user.referrer_id)
    if referrer is None:
        return

    session.add(
        ReferralBonus(
            referrer_id=referrer.tg_id,
            referred_id=user.tg_id,
            bonus_days=0,
            bonus_amount=settings.REFERRAL_BONUS_RUB,
        )
    )
    referrer.balance += settings.REFERRAL_BONUS_RUB
    session.add(BalanceTransaction(user_id=referrer.tg_id, delta=settings.REFERRAL_BONUS_RUB, reason="referral"))
    await session.flush()

    try:
        await bot.send_message(
            referrer.tg_id,
            f"🎁 Ваш реферал впервые пополнил баланс! Начислено {settings.REFERRAL_BONUS_RUB} руб.",
        )
    except Exception:
        pass
