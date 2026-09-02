from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import PromoCode
from bot.keyboards.admin import back_to_admin
from bot.services.promocodes import create_promo

router = Router(name="admin_promocodes")


@router.callback_query(F.data == "admin:promo")
async def promo_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    promos = (await session.execute(select(PromoCode).order_by(PromoCode.created_at.desc()).limit(20))).scalars().all()
    lines = []
    for p in promos:
        discount = f"{p.discount_percent}%" if p.discount_percent else f"{p.discount_amount} руб."
        exp = p.expires_at.strftime("%d.%m.%Y") if p.expires_at else "бессрочно"
        lines.append(f"`{p.code}` — {discount}, {p.used_count}/{p.max_activations}, до {exp}")
    text = "🎟 Промокоды\n\n" + ("\n".join(lines) if lines else "Пока нет промокодов") + (
        "\n\nЧтобы создать новый, отправьте сообщение в формате:\n"
        "`КОД скидка% лимит_активаций срок_дней`\n"
        "например: `START2026 20 100 30`\n"
        "(срок_дней — 0 = бессрочно)"
    )
    await callback.message.edit_text(text, reply_markup=back_to_admin(), parse_mode="Markdown")
    await callback.answer()


@router.message(F.text.regexp(r"^\S+\s+\d+\s+\d+\s+\d+$"))
async def create_promo_from_text(message: Message, session: AsyncSession) -> None:
    code, discount_percent, max_activations, expire_days = message.text.split()
    expires_at = (
        dt.datetime.utcnow() + dt.timedelta(days=int(expire_days)) if int(expire_days) > 0 else None
    )
    try:
        promo = await create_promo(
            session,
            code=code,
            discount_percent=int(discount_percent),
            discount_amount=None,
            max_activations=int(max_activations),
            expires_at=expires_at,
        )
    except Exception as exc:
        await message.answer(f"Не удалось создать промокод: {exc}")
        return

    await message.answer(f"Промокод `{promo.code}` создан.", parse_mode="Markdown")
