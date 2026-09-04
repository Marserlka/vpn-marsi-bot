from __future__ import annotations

import datetime as dt
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import BalanceTransaction, Payment, User
from bot.keyboards.admin import payment_confirmation_keyboard
from bot.keyboards.client import (
    back_to_menu,
    create_protocol_keyboard,
    create_region_keyboard,
    legal_docs_keyboard,
    payment_methods_keyboard,
    plans_keyboard,
    promo_prompt_keyboard,
    waiting_confirmation_keyboard,
)
from bot.services.payments import DEFAULT_PROVIDER, PROVIDERS
from bot.services.promocodes import PromoError, activate_promo, apply_discount, get_valid_promo
from bot.services.subscriptions import get_connection

logger = logging.getLogger("bot.purchase")
router = Router(name="purchase")

PLANS_TEXT = (
    "Выберите срок действия подключения.\n\n"
    "Оплачивая, вы подтверждаете, что принимаете:\n"
    "1️⃣ Политику конфиденциальности\n"
    "2️⃣ Условия использования\n\n"
    "📄 Все документы доступны по кнопке «Политика / Условия»."
)


class CreateStates(StatesGroup):
    waiting_name = State()


class BuyStates(StatesGroup):
    waiting_promo = State()


# --- new connection wizard: name -> protocol -> region -> plan -> ... -------

@router.callback_query(F.data == "create:start")
async def create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateStates.waiting_name)
    await callback.message.edit_text(
        "Введите название подключения (для себя, ни на что не влияет, например «Ноутбук» или «Телефон»):",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(CreateStates.waiting_name)
async def create_name_entered(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:64]
    if not name:
        await message.answer("Название не может быть пустым. Введите ещё раз:")
        return
    await state.update_data(mode="new", name=name)
    await state.set_state(None)
    await message.answer("Выберите протокол подключения:", reply_markup=create_protocol_keyboard())


@router.callback_query(F.data.startswith("create:protocol:"))
async def create_protocol_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    protocol = callback.data.split(":")[-1]
    await state.update_data(protocol=protocol)
    await callback.message.edit_text("Выберите регион сервера:", reply_markup=create_region_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("create:region:"))
async def create_region_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    region = callback.data.split(":")[-1]
    await state.update_data(region=region)
    await callback.message.edit_text(PLANS_TEXT, reply_markup=plans_keyboard())
    await callback.answer()


# --- extend an existing connection ------------------------------------------

@router.callback_query(F.data.startswith("menu:extend:"))
async def extend_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    conn_id = int(callback.data.split(":")[-1])
    conn = await get_connection(session, conn_id, callback.from_user.id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return
    await state.clear()
    await state.update_data(mode="extend", conn_id=conn_id)
    await callback.message.edit_text(PLANS_TEXT, reply_markup=plans_keyboard())
    await callback.answer()


# --- shared: plan -> promo -> payment method --------------------------------

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


def _build_payment(data: dict, user_id: int, price: int, provider: str, status: str, promo_code: str | None) -> Payment:
    plan = settings.plans[data["plan_idx"]]
    payment = Payment(
        user_id=user_id,
        amount=price,
        period_days=plan.period_days,
        provider=provider,
        status=status,
        promo_code=promo_code,
    )
    if data.get("mode") == "extend":
        payment.purpose = "extend_connection"
        payment.connection_id = data["conn_id"]
    else:
        payment.purpose = "new_connection"
        payment.new_connection_name = data.get("name", "Подключение")
        payment.new_connection_protocol = data.get("protocol", "amnezia")
    return payment


@router.callback_query(F.data == "buy:pay:balance")
async def pay_with_balance(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    data = await state.get_data()
    price = data.get("price", settings.plans[data["plan_idx"]].price_rub)

    user = await session.get(User, callback.from_user.id)
    if user.balance < price:
        await callback.answer("Недостаточно средств на балансе.", show_alert=True)
        return

    user.balance -= price
    session.add(BalanceTransaction(user_id=user.tg_id, delta=-price, reason="purchase"))

    payment = _build_payment(data, user.tg_id, price, "balance", "paid", data.get("promo_code"))
    payment.paid_at = dt.datetime.utcnow()
    session.add(payment)
    await session.flush()

    conn = await apply_paid_payment(session, payment)
    await state.clear()

    await callback.message.edit_text("✅ Оплачено с баланса! Подключение активировано.")
    if conn:
        await deliver_config(bot, session, conn)
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
    payment = _build_payment(data, callback.from_user.id, price, provider.name, "pending", promo_code)
    payment.invoice_id = invoice.invoice_id
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
                f"Тип: {'продление' if payment.purpose == 'extend_connection' else 'новое подключение'}\n"
                f"Промокод: {promo_code or '—'}",
                reply_markup=payment_confirmation_keyboard(payment_id),
            )
        except Exception:
            logger.exception("Failed to notify admin %s about payment %s", admin_id, payment_id)

    await callback.answer()


@router.callback_query(F.data == "buy:confirm_paid")
async def confirm_paid_by_user(callback: CallbackQuery) -> None:
    await callback.answer("Спасибо! Ожидайте подтверждения администратором.", show_alert=True)


async def deliver_config(bot: Bot, session: AsyncSession, conn) -> None:
    """Sends a connection's config (file or copyable text, depending on
    protocol — see profile.send_connection_config), if it has one."""
    from bot.handlers.profile import send_connection_config

    if not conn or not conn.awg_config:
        return
    await send_connection_config(bot, conn.user_id, conn)


async def apply_paid_payment(session: AsyncSession, payment: Payment):
    """Shared by the admin confirmation handler and balance-payment flow.

    Returns the affected Connection (or None for a balance top-up).
    Consumes the promo code and grants the referrer their recurring bonus
    (30% of this payment + 3 days) for connection payments — not for
    balance top-ups.
    """
    user = await session.get(User, payment.user_id)

    if payment.purpose == "balance_topup":
        user.balance += payment.amount
        session.add(BalanceTransaction(user_id=user.tg_id, delta=payment.amount, reason="topup"))
        await session.flush()
        return None

    from bot.services.referrals import grant_bonus_for_payment
    from bot.services.subscriptions import create_connection, extend_connection

    if payment.purpose == "extend_connection":
        conn = await get_connection(session, payment.connection_id, payment.user_id)
        if conn is None:
            raise ValueError(f"connection {payment.connection_id} not found for payment {payment.id}")
        conn = await extend_connection(session, conn, payment.period_days)
    else:
        conn = await create_connection(
            session,
            payment.user_id,
            payment.new_connection_name or "Подключение",
            payment.new_connection_protocol or "amnezia",
            "nl",
            payment.period_days,
        )
    payment.connection_id = conn.id

    if payment.promo_code:
        try:
            promo = await get_valid_promo(session, payment.promo_code, payment.user_id)
            await activate_promo(session, promo, payment.user_id)
        except PromoError:
            pass  # already consumed or expired between creation and confirmation; ignore

    await grant_bonus_for_payment(session, user, payment)
    return conn
