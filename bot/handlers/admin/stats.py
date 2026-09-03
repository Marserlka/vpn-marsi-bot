from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Connection, Payment, PromoActivation, User
from bot.keyboards.admin import admin_main_menu, back_to_admin

router = Router(name="admin_stats")


@router.message(Command("admin"))
async def admin_entry(message: Message) -> None:
    await message.answer("🔧 Админ-панель", reply_markup=admin_main_menu())


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text("🔧 Админ-панель", reply_markup=admin_main_menu())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    total_users = await session.scalar(select(func.count()).select_from(User))
    active_conns = await session.scalar(
        select(func.count()).select_from(Connection).where(Connection.status == "active")
    )

    today = dt.datetime.utcnow().date()
    month_start = today.replace(day=1)

    turnover_today = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "paid", func.date(Payment.paid_at) == today
        )
    )
    turnover_month = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "paid", Payment.paid_at >= month_start
        )
    )
    promo_used = await session.scalar(select(func.count()).select_from(PromoActivation))

    text = (
        "📊 Статистика\n\n"
        f"Всего пользователей: {total_users}\n"
        f"Активных подключений: {active_conns}\n"
        f"Оборот сегодня: {turnover_today} руб.\n"
        f"Оборот за месяц: {turnover_month} руб.\n"
        f"Использовано промокодов: {promo_used}"
    )
    await callback.message.edit_text(text, reply_markup=back_to_admin())
    await callback.answer()
