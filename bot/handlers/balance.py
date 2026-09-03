from __future__ import annotations

import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Payment, User
from bot.keyboards.admin import payment_confirmation_keyboard
from bot.keyboards.client import back_to_menu, balance_keyboard, waiting_confirmation_keyboard

logger = logging.getLogger("bot.balance")
router = Router(name="balance")


class TopupStates(StatesGroup):
    waiting_amount = State()


@router.callback_query(F.data == "menu:balance")
async def show_balance(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await session.get(User, callback.from_user.id)
    text = (
        f"💰 Баланс: {user.balance} руб.\n\n"
        "Баланс пополняется вручную и автоматически — за каждую оплату приглашённого "
        "друга вам начисляется 30% от суммы его покупки (см. «🎁 Бонус за друга»). "
        "Баланс можно потратить на оплату подписки."
    )
    await callback.message.edit_text(text, reply_markup=balance_keyboard())
    await callback.answer()


@router.callback_query(F.data == "balance:topup")
async def ask_topup_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TopupStates.waiting_amount)
    await callback.message.edit_text(
        "Введите сумму пополнения в рублях (целое число, минимум 10):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(TopupStates.waiting_amount)
async def topup_amount_entered(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("Введите целое число, например 100.")
        return
    if amount < 10:
        await message.answer("Минимальная сумма пополнения — 10 руб.")
        return

    await state.clear()

    payment = Payment(
        user_id=message.from_user.id,
        amount=amount,
        period_days=0,
        provider="manual",
        status="pending",
        purpose="balance_topup",
    )
    session.add(payment)
    await session.flush()
    payment_id = payment.id

    await message.answer(
        f"Счёт на {amount} руб. создан.\n\n"
        "Это тестовый режим оплаты (MVP) — реальный платёжный шлюз будет подключён на втором этапе. "
        "Нажмите «Я оплатил(а)», после чего администратор подтвердит платёж вручную.",
        reply_markup=waiting_confirmation_keyboard(),
    )

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"💳 Пополнение баланса #{payment_id}\n"
                f"Пользователь: {message.from_user.id} (@{message.from_user.username})\n"
                f"Сумма: {amount} руб.",
                reply_markup=payment_confirmation_keyboard(payment_id),
            )
        except Exception:
            logger.exception("Failed to notify admin %s about topup %s", admin_id, payment_id)
