from __future__ import annotations

import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.keyboards.admin import back_to_admin

logger = logging.getLogger("bot.broadcast")
router = Router(name="admin_broadcast")


class BroadcastStates(StatesGroup):
    waiting_text = State()


@router.callback_query(F.data == "admin:broadcast")
async def ask_broadcast_text(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting_text)
    await callback.message.edit_text(
        "Отправьте сообщение (текст, можно с фото) для рассылки всем пользователям:",
        reply_markup=back_to_admin(),
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_text)
async def do_broadcast(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.clear()
    user_ids = (await session.execute(select(User.tg_id))).scalars().all()

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await message.copy_to(uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # stay under Telegram's rate limits on large broadcasts

    await message.answer(f"Рассылка завершена. Доставлено: {sent}, ошибок: {failed}.")
