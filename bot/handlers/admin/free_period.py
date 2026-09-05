from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.admin import free_period_keyboard
from bot.services.free_period import disable_free_period, enable_free_period
from bot.services.settings import get_settings

router = Router(name="admin_free_period")


def _status_text(row) -> str:
    if row.free_period_enabled and row.free_period_started_at:
        elapsed = dt.datetime.utcnow() - row.free_period_started_at
        hours = int(elapsed.total_seconds() // 3600)
        status = f"включён ✅ (идёт {hours} ч.)"
    else:
        status = "выключен ❌"
    return (
        "🎁 Бесплатный общий период\n\n"
        f"Статус: {status}\n\n"
        "Пока включён: дни подписок (включая пробный период) не расходуются — "
        "сервер не деактивирует истёкшие подключения и не шлёт напоминания об истечении.\n"
        "При выключении даты окончания всех активных подключений сдвигаются вперёд "
        "ровно на длительность периода — никто не теряет дни."
    )


@router.callback_query(F.data == "admin:free_period")
async def free_period_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    row = await get_settings(session)
    await callback.message.edit_text(_status_text(row), reply_markup=free_period_keyboard(row.free_period_enabled))
    await callback.answer()


@router.callback_query(F.data == "admin:free_period:enable")
async def enable(callback: CallbackQuery, session: AsyncSession) -> None:
    await enable_free_period(session)
    row = await get_settings(session)
    await callback.message.edit_text(_status_text(row), reply_markup=free_period_keyboard(True))
    await callback.answer("Включено")


@router.callback_query(F.data == "admin:free_period:disable")
async def disable(callback: CallbackQuery, session: AsyncSession) -> None:
    duration = await disable_free_period(session)
    row = await get_settings(session)
    hours = int(duration.total_seconds() // 3600)
    await callback.message.edit_text(_status_text(row), reply_markup=free_period_keyboard(False))
    await callback.answer(f"Отключено. Все активные подключения сдвинуты на {hours} ч.")
