from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import BalanceTransaction, User
from bot.keyboards.admin import back_to_admin, user_actions_keyboard
from bot.services.subscriptions import activate_or_extend, deactivate, get_or_create_subscription

router = Router(name="admin_users")


class AdminStates(StatesGroup):
    searching_user = State()
    waiting_topup_amount = State()


@router.callback_query(F.data == "admin:users")
async def ask_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.searching_user)
    await callback.message.edit_text(
        "Введите Telegram ID или @username пользователя:", reply_markup=back_to_admin()
    )
    await callback.answer()


async def _find_user(session: AsyncSession, query: str) -> User | None:
    query = query.strip()
    if query.startswith("@"):
        return await session.scalar(select(User).where(User.username == query[1:]))
    if query.isdigit():
        return await session.get(User, int(query))
    return None


async def _render_user_card(message: Message, session: AsyncSession, user: User) -> None:
    sub = await get_or_create_subscription(session, user.tg_id)
    status = f"активна до {sub.expires_at.strftime('%d.%m.%Y')}" if sub.status == "active" and sub.expires_at else "неактивна"
    text = (
        f"👤 Пользователь {user.tg_id} (@{user.username})\n"
        f"Баланс: {user.balance} руб.\n"
        f"Подписка: {status}\n"
        f"AmneziaWG pubkey: {sub.awg_public_key or '—'}"
    )
    await message.answer(text, reply_markup=user_actions_keyboard(user.tg_id))


@router.message(AdminStates.searching_user)
async def do_search(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await _find_user(session, message.text)
    if user is None:
        await message.answer("Пользователь не найден. Попробуйте ещё раз или введите /admin для выхода.")
        return
    await state.clear()
    await _render_user_card(message, session, user)


@router.callback_query(F.data.startswith("admin:extend:"))
async def extend_user(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, user_id_str, days_str = callback.data.split(":")
    user_id = int(user_id_str)
    try:
        await activate_or_extend(session, user_id, int(days_str))
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        raise
    await callback.answer("Подписка продлена", show_alert=True)
    user = await session.get(User, user_id)
    if user:
        await _render_user_card(callback.message, session, user)


@router.callback_query(F.data.startswith("admin:disable:"))
async def disable_user(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.split(":")[-1])
    sub = await get_or_create_subscription(session, user_id)
    try:
        await deactivate(session, sub)
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        raise
    await callback.answer("Подписка отключена", show_alert=True)
    user = await session.get(User, user_id)
    if user:
        await _render_user_card(callback.message, session, user)


@router.callback_query(F.data.startswith("admin:topup:"))
async def ask_topup_amount(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminStates.waiting_topup_amount)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer("Введите сумму пополнения в рублях (можно отрицательную для списания):")
    await callback.answer()


@router.message(AdminStates.waiting_topup_amount)
async def do_topup(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("Введите целое число, например 50 или -20.")
        return

    data = await state.get_data()
    target_user_id = data["target_user_id"]
    user = await session.get(User, target_user_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return

    user.balance += amount
    session.add(
        BalanceTransaction(
            user_id=target_user_id,
            delta=amount,
            reason="admin_topup",
            created_by_admin_id=message.from_user.id,
        )
    )
    await session.flush()
    await state.clear()
    await message.answer(f"Готово. Новый баланс пользователя {target_user_id}: {user.balance} руб.")

    try:
        await bot.send_message(target_user_id, f"Ваш баланс изменён администратором на {amount:+d} руб.")
    except Exception:
        pass
