from __future__ import annotations

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Payment, ReferralBonus, User


async def register_referral(session: AsyncSession, user: User, referrer_id: int) -> None:
    if user.referrer_id is not None or referrer_id == user.tg_id:
        return
    referrer = await session.get(User, referrer_id)
    if referrer is None:
        return
    user.referrer_id = referrer_id
    await session.flush()


async def pending_bonus_days(session: AsyncSession, referrer_id: int) -> int:
    """Sum of bonus days this referrer has earned but not yet applied to a
    connection (ReferralBonus.connection_id IS NULL — see the model docstring)."""
    total = await session.scalar(
        select(func.sum(ReferralBonus.bonus_days)).where(
            ReferralBonus.referrer_id == referrer_id, ReferralBonus.connection_id.is_(None)
        )
    )
    return total or 0


async def claim_pending_bonus_days(session: AsyncSession, referrer_id: int, connection_id: int) -> int:
    """Marks every pending bonus for this referrer as applied to `connection_id`
    and returns the total number of days claimed (0 if there was nothing
    pending). Caller is responsible for actually extending the connection."""
    bonuses = (
        await session.execute(
            select(ReferralBonus).where(
                ReferralBonus.referrer_id == referrer_id, ReferralBonus.connection_id.is_(None)
            )
        )
    ).scalars().all()
    total_days = sum(b.bonus_days for b in bonuses)
    for b in bonuses:
        b.connection_id = connection_id
    return total_days


async def grant_bonus_for_payment(session: AsyncSession, bot: Bot, user: User, payment: Payment) -> None:
    """Called after every payment is marked paid (not just the first one):
    the referrer earns a flat REFERRAL_BONUS_DAYS-day bonus each time their
    referral pays — no cash payout (removed 2026-09-05, see TZ). The bonus
    starts out pending (connection_id=NULL) and the referrer is asked which
    of their own connections to add the days to; if they have none right
    now, it stays pending until they claim it from a connection card later."""
    if user.referrer_id is None or not settings.REFERRAL_BONUS_DAYS:
        return

    bonus = ReferralBonus(
        referrer_id=user.referrer_id,
        referred_id=user.tg_id,
        bonus_days=settings.REFERRAL_BONUS_DAYS,
        bonus_amount=0,
    )
    session.add(bonus)
    await session.flush()

    referrer = await session.get(User, user.referrer_id)
    if referrer is None:
        return

    from bot.keyboards.client import referral_bonus_keyboard
    from bot.services.subscriptions import list_connections

    referrer_conns = await list_connections(session, referrer.tg_id)
    active_conns = [c for c in referrer_conns if c.status == "active"]

    try:
        if active_conns:
            await bot.send_message(
                referrer.tg_id,
                f"🎁 Ваш реферал оплатил подписку! Начислено {settings.REFERRAL_BONUS_DAYS} дн. "
                "Выберите, к какому подключению их добавить:",
                reply_markup=referral_bonus_keyboard(active_conns),
            )
        else:
            await bot.send_message(
                referrer.tg_id,
                f"🎁 Ваш реферал оплатил подписку! Начислено {settings.REFERRAL_BONUS_DAYS} дн. "
                "У вас пока нет активных подключений — как только создадите одно, "
                "сможете применить эти дни к нему из карточки подключения.",
            )
    except Exception:
        pass
