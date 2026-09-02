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
from bot.keyboards.client import (
    back_to_menu,
    payment_methods_keyboard,
    plans_keyboard,
    promo_prompt_keyboard,
    waiting_confirmation_keyboard,
)
from bot.services.payments import DEFAULT_PROVIDER, PROVIDERS
from bot.services.promocodes import PromoError, activate_promo, apply_discount, get_valid_promo

logger = logging.getLogger("bot.purchase")
router = Router(name="purchase")


class BuyStates(StatesGroup):
    waiting_promo = State()


@router.callback_query(F.data == "menu:buy")
async def choose_plan(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Выберите тариф:", reply_markup=plans_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("buy:plan:"))
async def plan_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":")[-1])
    plan = settings.plans[idx]
    await state.update_data(plan_idx=idx, price=plan.price_rub)
    await callback.message.edit_text(
        f"Тариф: {plan.period_days} дн. — {plan.price_rub} руб.\n\nЕсть промокод?",
        reply_markup=promo_prompt_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "buy:promo")
async def ask_promo(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyStates.waiting_promo)
    await callback.message.edit_text("Введите промокод сообщением:", reply_markup=back_to_menu())
    await callback.answer()


@router.message(BuyStates.waiting_promo)
async def promo_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    plan = settings.plans[data["plan_idx"]]
    try:
        promo = await get_valid_promo(session, message.text, message.from_user.id)
    except PromoError as exc:
        await message.answer(f"❌ {exc}. Попробуйте другой промокод или нажмите «Пропустить».",
                              reply_markup=promo_prompt_keyboard())
        return

    price = apply_discount(plan.price_rub, promo)
    await state.update_data(price=price, promo_code=promo.code)
    await state.set_state(None)
    await message.answer(
        f"Промокод применён! Итоговая цена: {price} руб.\n\nВыберите способ оплаты:",
        reply_markup=payment_methods_keyboard(),
    )


@router.callback_query(F.data == "buy:skip_promo")
async def skip_promo(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    price = data.get("price")
    await callback.message.edit_text(
        f"Итоговая цена: {price} руб.\n\nВыберите способ оплаты:",
        reply_markup=payment_methods_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:pay:"))
async def create_payment(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    provider_name = callback.data.split(":")[-1]
    provider = PROVIDERS.get(provider_name, PROVIDERS[DEFAULT_PROVIDER])
    data = await state.get_data()
    plan = settings.plans[data["plan_idx"]]
    price = data.get("price", plan.price_rub)
    promo_code = data.get("promo_code")

    invoice = await provider.create_invoice(
        user_id=callback.from_user.id, amount=price, description=f"VPN MARSI {plan.period_days} дн."
    )
    payment = Payment(
        user_id=callback.from_user.id,
        amount=price,
        period_days=plan.period_days,
        provider=provider.name,
        status="pending",
        promo_code=promo_code,
        invoice_id=invoice.invoice_id,
    )
    session.add(payment)
    await session.flush()
    payment_id = payment.id

    await callback.message.edit_text(
        f"Счёт на {price} руб. создан.\n\n"
        "Это тестовый режим оплаты (MVP) — реальный платёжный шлюз будет подключён на втором этапе. "
        "Нажмите «Я оплатил(а)», после чего администратор подтвердит платёж вручную.",
        reply_markup=waiting_confirmation_keyboard(),
    )
    await state.clear()

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"💰 Новый платёж #{payment_id}\n"
                f"Пользователь: {callback.from_user.id} (@{callback.from_user.username})\n"
                f"Сумма: {price} руб., период: {plan.period_days} дн.\n"
                f"Промокод: {promo_code or '—'}",
                reply_markup=payment_confirmation_keyboard(payment_id),
            )
        except Exception:
            logger.exception("Failed to notify admin %s about payment %s", admin_id, payment_id)

    await callback.answer()


@router.callback_query(F.data == "buy:confirm_paid")
async def confirm_paid_by_user(callback: CallbackQuery) -> None:
    await callback.answer("Спасибо! Ожидайте подтверждения администратором.", show_alert=True)


async def apply_paid_payment(session: AsyncSession, payment: Payment) -> None:
    """Shared by the admin confirmation handler: activates the subscription,
    consumes the promo code and grants a referral bonus on first payment."""
    from bot.services.referrals import grant_bonus_if_first_payment
    from bot.services.subscriptions import activate_or_extend

    user = await session.get(User, payment.user_id)
    await activate_or_extend(session, payment.user_id, payment.period_days)

    if payment.promo_code:
        try:
            promo = await get_valid_promo(session, payment.promo_code, payment.user_id)
            await activate_promo(session, promo, payment.user_id)
        except PromoError:
            pass  # already consumed or expired between creation and confirmation; ignore

    await grant_bonus_if_first_payment(session, user)
