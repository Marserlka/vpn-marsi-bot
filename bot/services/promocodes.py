from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import PromoActivation, PromoCode


class PromoError(Exception):
    pass


async def get_valid_promo(session: AsyncSession, code: str, user_id: int) -> PromoCode:
    promo = await session.scalar(select(PromoCode).where(PromoCode.code == code.strip().upper()))
    if promo is None or not promo.is_active:
        raise PromoError("Промокод не найден")
    if promo.expires_at and promo.expires_at < dt.datetime.utcnow():
        raise PromoError("Срок действия промокода истёк")
    if promo.used_count >= promo.max_activations:
        raise PromoError("Лимит активаций промокода исчерпан")
    already_used = await session.scalar(
        select(PromoActivation).where(PromoActivation.promo_id == promo.id, PromoActivation.user_id == user_id)
    )
    if already_used:
        raise PromoError("Вы уже использовали этот промокод")
    return promo


def apply_discount(price: int, promo: PromoCode) -> int:
    if promo.discount_percent:
        price = price - (price * promo.discount_percent // 100)
    if promo.discount_amount:
        price = price - promo.discount_amount
    return max(price, 0)


async def activate_promo(session: AsyncSession, promo: PromoCode, user_id: int) -> None:
    promo.used_count += 1
    session.add(PromoActivation(promo_id=promo.id, user_id=user_id))
    await session.flush()


async def create_promo(
    session: AsyncSession,
    *,
    code: str,
    discount_percent: int | None,
    discount_amount: int | None,
    max_activations: int,
    expires_at: dt.datetime | None,
) -> PromoCode:
    promo = PromoCode(
        code=code.strip().upper(),
        discount_percent=discount_percent,
        discount_amount=discount_amount,
        max_activations=max_activations,
        expires_at=expires_at,
    )
    session.add(promo)
    await session.flush()
    return promo
