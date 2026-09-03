from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Payment, Subscription

router = Router(name="admin_payments")


@router.callback_query(F.data.startswith("admin:confirm_payment:"))
async def confirm_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    from bot.handlers.purchase import apply_paid_payment

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
        await bot.send_message(payment.user_id, "✅ Оплата подтверждена! Подписка активирована.")
        sub = await session.scalar(select(Subscription).where(Subscription.user_id == payment.user_id))
        if sub and sub.awg_config:
            file = BufferedInputFile(sub.awg_config.encode(), filename="vpnmarsi.conf")
            await bot.send_document(
                payment.user_id,
                file,
                caption=(
                    "Ваш конфиг AmneziaWG.\n\n"
                    "1. Установите приложение AmneziaVPN.\n"
                    "2. «Добавить конфигурацию» → «Импортировать из файла» → выберите этот файл.\n"
                    "3. Подключитесь.\n\n"
                    "⚠️ 1 подписка = 1 устройство."
                ),
            )
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
