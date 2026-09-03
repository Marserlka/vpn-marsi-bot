from __future__ import annotations

import datetime as dt
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, Payment, Subscription, User
from bot.keyboards.admin import payment_confirmation_keyboard
from bot.keyboards.client import (
    back_to_menu,
    legal_docs_keyboard,
    payment_methods_keyboard,
    plans_keyboard,
    promo_prompt_keyboard,
    waiting_confirmation_keyboard,
)
from bot.services.payments import DEFAULT_PROVIDER, PROVIDERS
from bot.services.promocodes import PromoError, activate_promo, apply_discount, get_valid_promo

logger = logging.getLogger("bot.purchase")
router = Router(name="purchase")

PLANS_TEXT = (
    "Выберите срок продления подписки.\n\n"
    "✅ Подписка включает доступ для 1 устройства.\n\n"
    "Оплачивая подписку, вы подтверждаете, что принимаете:\n"
    "1️⃣ Политику конфиденциальности\n"
    "2️⃣ Условия использования\n\n"
    "📄 Все документы доступны по кнопке «Политика / Условия»."
)


class BuyStates(StatesGroup):
    waiting_promo = State()


@router.callback_query(F.data == "menu:buy")
async def choose_plan(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(PLANS_TEXT, reply_markup=plans_keyboard())
    await callback.answer()


@router.callback_query(F.data == "buy:legal")
async def show_legal(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📄 Правовые документы сервиса:", reply_markup=legal_docs_keyboard()
    )
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


async def _show_payment_methods(target, session: AsyncSession, user_id: int, price: int, edit: bool) -> None:
    user = await session.get(User, user_id)
    can_pay_from_balance = bool(user and user.balance >= price)
    text = f"Итоговая цена: {price} руб.\n\nВыберите способ оплаты:"
    keyboard = payment_methods_keyboard(can_pay_from_balance)
    if edit:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


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
    await message.answer(f"Промокод применён! Итоговая цена: {price} руб.")
    await _show_payment_methods(message, session, message.from_user.id, price, edit=False)


@router.callback_query(F.data == "buy:skip_promo")
async def skip_promo(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    price = data.get("price")
    await _show_payment_methods(callback.message, session, callback.from_user.id, price, edit=True)
    await callback.answer()


@router.callback_query(F.data == "buy:pay:balance")
async def pay_with_balance(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    data = await state.get_data()
    plan = settings.plans[data["plan_idx"]]
    price = data.get("price", plan.price_rub)
    promo_code = data.get("promo_code")

    user = await session.get(User, callback.from_user.id)
    if user.balance < price:
        await callback.answer("Недостаточно средств на балансе.", show_alert=True)
        return

    user.balance -= price
    session.add(BalanceTransaction(user_id=user.tg_id, delta=-price, reason="purchase"))

    payment = Payment(
        user_id=user.tg_id,
        amount=price,
        period_days=plan.period_days,
        provider="balance",
        status="paid",
        purpose="subscription",
        promo_code=promo_code,
        paid_at=dt.datetime.utcnow(),
    )
    session.add(payment)
    await session.flush()

    await apply_paid_payment(session, payment)
    await state.clear()

    await callback.message.edit_text("✅ Оплачено с баланса! Подписка активирована.")
    await deliver_config(bot, session, user.tg_id)
    await callback.answer()


@router.callback_query(F.data.startswith("buy:pay:"))
async def create_payment(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    provider_name = callback.data.split(":")[-1]
    if provider_name == "balance":
        return  # handled by pay_with_balance above
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
        purpose="subscription",
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


async def deliver_config(bot: Bot, session: AsyncSession, user_id: int) -> None:
    """Sends the user's current VPN .conf as a document, if they have one."""
    from sqlalchemy import select

    from bot.handlers.profile import PROTOCOL_APP, PROTOCOL_IMPORT_HINT, PROTOCOL_LABELS

    sub = await session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if not sub or not sub.awg_config:
        return
    app_name = PROTOCOL_APP.get(sub.protocol, "приложение AmneziaVPN")
    import_hint = PROTOCOL_IMPORT_HINT.get(sub.protocol, PROTOCOL_IMPORT_HINT["amnezia"])
    limit_note = (
        "⚠️ 1 подписка = 1 устройство."
        if sub.protocol in ("amnezia", "wireguard")
        else "ℹ️ Ограничение на 1 устройство для этого протокола пока не действует."
    )
    file = BufferedInputFile(sub.awg_config.encode(), filename="vpnmarsi.conf")
    await bot.send_document(
        user_id,
        file,
        caption=(
            f"Ваш конфиг ({PROTOCOL_LABELS.get(sub.protocol, sub.protocol)}).\n\n"
            f"1. Установите {app_name}.\n"
            f"2. {import_hint}.\n"
            "3. Подключитесь.\n\n"
            f"{limit_note}"
        ),
    )


async def apply_paid_payment(session: AsyncSession, payment: Payment) -> None:
    """Shared by the admin confirmation handler and balance-payment flow.

    For a subscription payment: activates it, consumes the promo code and
    grants the referrer their recurring bonus (30% of this payment + 3 days).
    For a balance top-up: just credits the user's balance — no subscription,
    promo, or referral bonus involved.
    """
    user = await session.get(User, payment.user_id)

    if payment.purpose == "balance_topup":
        user.balance += payment.amount
        session.add(BalanceTransaction(user_id=user.tg_id, delta=payment.amount, reason="topup"))
        await session.flush()
        return

    from bot.services.referrals import grant_bonus_for_payment
    from bot.services.subscriptions import activate_or_extend

    await activate_or_extend(session, payment.user_id, payment.period_days)

    if payment.promo_code:
        try:
            promo = await get_valid_promo(session, payment.promo_code, payment.user_id)
            await activate_promo(session, promo, payment.user_id)
        except PromoError:
            pass  # already consumed or expired between creation and confirmation; ignore

    await grant_bonus_for_payment(session, user, payment)
