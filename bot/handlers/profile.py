from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Payment, ReferralBonus, User
from bot.keyboards.client import back_to_menu
from bot.services.subscriptions import get_or_create_subscription

router = Router(name="profile")


@router.callback_query(F.data == "menu:profile")
async def profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await session.get(User, callback.from_user.id)
    sub = await get_or_create_subscription(session, callback.from_user.id)

    if sub.status == "active" and sub.expires_at:
        status_line = f"Статус: ✅ Активна до {sub.expires_at.strftime('%d.%m.%Y')}"
    else:
        status_line = "Статус: ❌ Истекла"

    key_line = f"\n\nВаша ссылка для подключения:\n`{sub.subscription_url}`" if sub.subscription_url else ""

    text = (
        f"👤 Личный кабинет\n\n"
        f"{status_line}\n"
        f"Баланс: {user.balance} руб.\n"
        f"{key_line}\n\n"
        f"⚠️ 1 подписка предназначена только для 1 устройства. При одновременном "
        f"включении на двух устройствах доступ автоматически блокируется."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "menu:referral")
async def referral(callback: CallbackQuery, session: AsyncSession) -> None:
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"

    invited_count = await session.scalar(
        select(func.count()).select_from(User).where(User.referrer_id == callback.from_user.id)
    )
    paid_count = await session.scalar(
        select(func.count(func.distinct(Payment.user_id)))
        .select_from(Payment)
        .join(User, User.tg_id == Payment.user_id)
        .where(User.referrer_id == callback.from_user.id, Payment.status == "paid")
    )
    bonuses = await session.execute(
        select(ReferralBonus).where(ReferralBonus.referrer_id == callback.from_user.id)
    )
    bonuses = bonuses.scalars().all()
    total_days = sum(b.bonus_days for b in bonuses)
    total_amount = sum(b.bonus_amount for b in bonuses)

    text = (
        "👥 Реферальная система\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"Приглашено: {invited_count or 0}\n"
        f"Оплатили подписку: {paid_count or 0}\n"
        f"Заработано: {total_amount} руб." + (f", {total_days} дн." if total_days else "")
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()
