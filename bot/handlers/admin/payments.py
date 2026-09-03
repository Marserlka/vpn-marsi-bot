from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Payment

router = Router(name="admin_payments")


@router.callback_query(F.data.startswith("admin:confirm_payment:"))
async def confirm_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    from bot.handlers.purchase import apply_paid_payment, deliver_config

    payment_id = int(callback.data.split(":")[-1])
    payment = await session.get(Payment, payment_id)
    if payment is None:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    if payment.status == "paid":
        await callback.answer("Уже подтверждён", show_alert=True)
        return

    payment.status = "paid"
    payment.paid_at = dt.datetime.utcnow()
    await apply_paid_payment(session, payment)

    await callback.message.edit_text(callback.message.text + "\n\n✅ Подтверждено")
    await callback.answer("Платёж подтверждён")

    try:
        if payment.purpose == "balance_topup":
            await bot.send_message(payment.user_id, f"✅ Баланс пополнен на {payment.amount} руб.")
        else:
            await bot.send_message(payment.user_id, "✅ Оплата подтверждена! Подписка активирована.")
            await deliver_config(bot, session, payment.user_id)
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin:reject_payment:"))
async def reject_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    payment_id = int(callback.data.split(":")[-1])
    payment = await session.get(Payment, payment_id)
    if payment is None:
        await callback.answer("Платёж не найден", show_alert=True)
        return

    payment.status = "failed"
    await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено")
    await callback.answer("Платёж отклонён")

    try:
        await bot.send_message(payment.user_id, "❌ Оплата не подтверждена. Обратитесь в поддержку.")
    except Exception:
        pass
