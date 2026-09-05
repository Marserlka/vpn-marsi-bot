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
from bot.keyboards.client import (
    back_to_menu,
    create_confirm_keyboard,
    create_protocol_keyboard,
    create_region_keyboard,
    legal_docs_keyboard,
)
from bot.services.subscriptions import MARZBAN_FAMILY, charge_connection_day, create_connection
from bot.utils.emoji import pe

logger = logging.getLogger("bot.purchase")
router = Router(name="purchase")


class CreateStates(StatesGroup):
    waiting_name = State()


# --- new connection wizard: name -> protocol -> [region] -> confirm/trial --

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
    await state.update_data(name=name)
    await state.set_state(None)
    await message.answer("Выберите протокол подключения:", reply_markup=create_protocol_keyboard())


@router.callback_query(F.data.startswith("create:protocol:"))
async def create_protocol_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    protocol = callback.data.split(":")[-1]
    await state.update_data(protocol=protocol)

    # VLESS/Shadowsocks are delivered as one Marzban subscription URL that
    # bundles every inbound the user is assigned to (see subscriptions.py:
    # _provision) — there's nothing to pick a single region *for* the way
    # there is for a WireGuard-family peer bound to one specific server, so
    # skip straight to the confirm screen instead of asking (2026-09-05).
    if protocol in MARZBAN_FAMILY:
        await _show_create_confirm(callback, state, session, "all")
    else:
        await callback.message.edit_text("Выберите регион сервера:", reply_markup=create_region_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("create:region:"))
async def create_region_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    region = callback.data.split(":")[-1]
    await _show_create_confirm(callback, state, session, region)
    await callback.answer()


async def _show_create_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession, region: str) -> None:
    await state.update_data(region=region)
    user = await session.get(User, callback.from_user.id)
    show_trial = bool(user and not user.trial_used)

    text = (
        f"{pe('price')} Стоимость: {settings.PRICE_PER_DAY_RUB} руб./день, списывается с баланса ежедневно.\n"
        f"Ваш баланс: {user.balance} руб.\n\n"
        f"⚠️ Подключение нельзя удалить в течение {settings.MIN_CONNECTION_AGE_DAYS} дней после создания.\n\n"
        "Создавая подключение, вы подтверждаете, что принимаете:\n"
        "1️⃣ Политику конфиденциальности\n"
        "2️⃣ Условия использования"
    )
    if show_trial:
        text += f"\n\n🎁 Для вас как для нового пользователя доступен {settings.TRIAL_DAYS}-дневный бесплатный период."
    await callback.message.edit_text(text, reply_markup=create_confirm_keyboard(show_trial))


@router.callback_query(F.data == "buy:legal")
async def show_legal(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📄 Правовые документы сервиса:", reply_markup=legal_docs_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "create:trial")
async def trial_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    user = await session.get(User, callback.from_user.id)
    if user is None or user.trial_used:
        await callback.answer("Пробный период уже использован.", show_alert=True)
        return

    data = await state.get_data()
    user.trial_used = True
    conn = await create_connection(
        session,
        callback.from_user.id,
        data.get("name", "Подключение"),
        data.get("protocol", "amnezia"),
        data.get("region", "de"),
        trial=True,
    )
    await state.clear()

    await callback.message.edit_text(
        f"🎁 Пробный период на {settings.TRIAL_DAYS} дня активирован! Подключение создано."
    )
    await deliver_config(bot, session, conn)
    await callback.answer()


@router.callback_query(F.data == "create:confirm")
async def create_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    user = await session.get(User, callback.from_user.id)
    if user is None or user.balance < settings.PRICE_PER_DAY_RUB:
        await callback.answer(
            f"Недостаточно средств на балансе. Нужно минимум {settings.PRICE_PER_DAY_RUB} руб. "
            "Пополните баланс и попробуйте снова.",
            show_alert=True,
        )
        return

    data = await state.get_data()
    conn = await create_connection(
        session,
        callback.from_user.id,
        data.get("name", "Подключение"),
        data.get("protocol", "amnezia"),
        data.get("region", "de"),
        trial=False,
    )
    await charge_connection_day(session, conn)
    await state.clear()

    await callback.message.edit_text(
        f"✅ Подключение создано! Списано {settings.PRICE_PER_DAY_RUB}{pe('price')} руб. за первый день."
    )
    await deliver_config(bot, session, conn)
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


async def apply_paid_payment(session: AsyncSession, bot: Bot, payment: Payment) -> None:
    """Confirms a manual balance top-up (the only kind of Payment there is
    since 2026-09-05 — connections are no longer bought via invoice, they're
    billed per-day straight out of the balance, see bot/services/subscriptions.py).
    Credits the balance and, if this is the referred user's first-ever
    top-up, grants their referrer the flat cash bonus."""
    user = await session.get(User, payment.user_id)
    user.balance += payment.amount
    session.add(BalanceTransaction(user_id=user.tg_id, delta=payment.amount, reason="topup"))
    await session.flush()

    from bot.services.referrals import grant_referral_bonus_if_first_topup

    await grant_referral_bonus_if_first_topup(session, bot, user)
